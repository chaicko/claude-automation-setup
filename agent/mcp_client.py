"""
MCP subprocess manager and tool executor.

Starts each MCP server as a subprocess, discovers tools via tools/list,
and executes tool calls via JSON-RPC over stdin/stdout.
"""

import asyncio
import json
import logging
import subprocess
import sys
from typing import Any

logger = logging.getLogger(__name__)


class MCPClient:
    """Manages a single MCP server subprocess."""

    def __init__(self, name: str, command: list[str], env: dict | None = None):
        self.name = name
        self.command = command
        self.env = env
        self._proc: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._tools: list[dict] = []

    async def start(self):
        """Start the MCP server subprocess."""
        import os
        proc_env = os.environ.copy()
        if self.env:
            proc_env.update(self.env)

        self._proc = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=proc_env,
        )
        logger.info(f"Started MCP server '{self.name}' (pid={self._proc.pid})")

        # Initialize the MCP session
        await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "claude-agent", "version": "1.0.0"},
        })

        # Discover tools
        result = await self._send_request("tools/list", {})
        self._tools = result.get("tools", [])
        logger.info(f"MCP server '{self.name}' has {len(self._tools)} tools: "
                    f"{[t['name'] for t in self._tools]}")

    async def stop(self):
        """Stop the MCP server subprocess."""
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._proc.kill()
            logger.info(f"Stopped MCP server '{self.name}'")

    @property
    def tools(self) -> list[dict]:
        return self._tools

    def tools_as_openai_format(self) -> list[dict]:
        """Convert MCP tool definitions to OpenAI function-calling format."""
        openai_tools = []
        for tool in self._tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": f"{self.name}__{tool['name']}",  # namespace by server
                    "description": tool.get("description", ""),
                    "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
                },
            })
        return openai_tools

    async def call_tool(self, tool_name: str, arguments: dict) -> Any:
        """Execute a tool call and return the result."""
        logger.info(f"Calling tool '{tool_name}' on MCP server '{self.name}'")
        result = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        # MCP tools/call returns { content: [...], isError: bool }
        if result.get("isError"):
            raise RuntimeError(f"MCP tool '{tool_name}' returned error: {result}")
        content = result.get("content", [])
        # Flatten content blocks to string
        parts = []
        for block in content:
            if block.get("type") == "text":
                parts.append(block["text"])
            else:
                parts.append(json.dumps(block))
        return "\n".join(parts)

    async def _send_request(self, method: str, params: dict) -> dict:
        """Send a JSON-RPC request and await the response."""
        if self._proc is None:
            raise RuntimeError(f"MCP server '{self.name}' not started")

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        payload = json.dumps(request) + "\n"
        self._proc.stdin.write(payload.encode())
        await self._proc.stdin.drain()

        # Read response line
        line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=30.0)
        if not line:
            stderr = await self._proc.stderr.read(4096)
            raise RuntimeError(
                f"MCP server '{self.name}' closed stdout. stderr: {stderr.decode()}"
            )
        response = json.loads(line.decode())
        if "error" in response:
            raise RuntimeError(
                f"MCP JSON-RPC error from '{self.name}': {response['error']}"
            )
        return response.get("result", {})


class MCPManager:
    """Manages multiple MCP servers and routes tool calls."""

    def __init__(self):
        self._servers: dict[str, MCPClient] = {}

    def add_server(self, name: str, command: list[str], env: dict | None = None):
        self._servers[name] = MCPClient(name, command, env)

    async def start_all(self):
        tasks = [s.start() for s in self._servers.values()]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for name, result in zip(self._servers.keys(), results):
            if isinstance(result, Exception):
                logger.error(f"Failed to start MCP server '{name}': {result}")

    async def stop_all(self):
        tasks = [s.stop() for s in self._servers.values()]
        await asyncio.gather(*tasks, return_exceptions=True)

    def all_tools_openai_format(self) -> list[dict]:
        """Collect all tools from all servers in OpenAI format."""
        tools = []
        for server in self._servers.values():
            tools.extend(server.tools_as_openai_format())
        return tools

    async def execute_tool_call(self, namespaced_tool_name: str, arguments: dict) -> str:
        """Execute a tool call. Tool names are namespaced as 'server__tool'."""
        if "__" not in namespaced_tool_name:
            raise ValueError(f"Invalid namespaced tool name: '{namespaced_tool_name}'")
        server_name, tool_name = namespaced_tool_name.split("__", 1)
        if server_name not in self._servers:
            raise ValueError(f"Unknown MCP server: '{server_name}'")
        return await self._servers[server_name].call_tool(tool_name, arguments)
