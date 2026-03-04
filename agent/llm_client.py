"""
Unified LLM client: Ollama (local, default) or Anthropic API (optional fallback).

Ollama uses the OpenAI-compatible API at http://localhost:11434/v1.
Both backends use the same OpenAI function-calling format for tools.
"""

import json
import logging
import os
from typing import Any

import openai

logger = logging.getLogger(__name__)


class LLMClient:
    """Unified client for Ollama or Anthropic, with agentic tool-use loop."""

    def __init__(self):
        self.provider = os.getenv("MODEL_PROVIDER", "ollama").lower()
        self.ollama_model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        self.anthropic_model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

        if self.provider == "ollama":
            self._client = openai.OpenAI(
                base_url=self.ollama_base_url,
                api_key="ollama",  # Ollama ignores the key
            )
            self._model = self.ollama_model
            logger.info(f"LLM: Ollama @ {self.ollama_base_url}, model={self._model}")
        elif self.provider == "anthropic":
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY is required when MODEL_PROVIDER=anthropic")
            self._client = openai.OpenAI(
                base_url="https://api.anthropic.com/v1",
                api_key=api_key,
                default_headers={"anthropic-version": "2023-06-01"},
            )
            self._model = self.anthropic_model
            logger.info(f"LLM: Anthropic API, model={self._model}")
        else:
            raise ValueError(f"Unknown MODEL_PROVIDER: '{self.provider}'. Use 'ollama' or 'anthropic'.")

    async def run_agent_loop(
        self,
        system_prompt: str,
        user_message: str,
        tools: list[dict],
        tool_executor,  # async callable(tool_name, args) -> str
        max_iterations: int = 10,
    ) -> str:
        """
        Run the agentic tool-use loop:
        1. Send messages + tools to LLM
        2. If LLM returns tool calls, execute them and append results
        3. Loop until LLM returns a final text response or max_iterations reached
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        for iteration in range(max_iterations):
            logger.debug(f"LLM iteration {iteration + 1}/{max_iterations}")

            kwargs: dict[str, Any] = {
                "model": self._model,
                "messages": messages,
            }
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"

            response = self._client.chat.completions.create(**kwargs)
            message = response.choices[0].message

            # Append assistant message (with or without tool calls)
            messages.append(message.model_dump(exclude_none=True))

            # If no tool calls, we have the final answer
            if not message.tool_calls:
                return message.content or ""

            # Execute all tool calls
            for tool_call in message.tool_calls:
                fn_name = tool_call.function.name
                try:
                    fn_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    fn_args = {}

                logger.info(f"Executing tool: {fn_name}({fn_args})")
                try:
                    result = await tool_executor(fn_name, fn_args)
                    result_str = str(result)
                except Exception as e:
                    result_str = f"ERROR: {e}"
                    logger.error(f"Tool '{fn_name}' failed: {e}")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_str,
                })

        logger.warning("Agent loop reached max_iterations without final answer")
        return "Agent loop exhausted without completing the task."
