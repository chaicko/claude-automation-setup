# Adding New Capabilities

## Adding a new handler

Handlers are Python classes that run during each agent cycle.

1. Create `agent/handlers/my_handler.py`:

```python
import logging
from mcp_client import MCPManager
from llm_client import LLMClient
from approval_loop import create_pending_action

logger = logging.getLogger(__name__)

class MyHandler:
    def __init__(self, mcp_manager: MCPManager, llm: LLMClient, notify_number: str):
        self.mcp = mcp_manager
        self.llm = llm
        self.notify_number = notify_number

    async def process(self):
        logger.info("MyHandler: checking...")
        # ... your logic here
        # To request approval:
        action_id = create_pending_action(
            action_type="my_action_type",
            payload={"key": "value"},
            whatsapp_message=f"Do X?\nReply YES {action_id} / NO {action_id}",
        )
        await self.mcp.execute_tool_call("whatsapp__send_message", {
            "phone": self.notify_number,
            "message": f"Do X?\nReply YES {action_id} / NO {action_id}",
        })
```

2. Register the action type in `claude-agent.py`'s `execute_action()`:

```python
elif action_type == "my_action_type":
    result = await mcp_manager.execute_tool_call("some_mcp__some_tool", payload)
    return f"Done: {result[:100]}"
```

3. Add the handler to `run_cycle()`:

```python
from handlers.my_handler import MyHandler

async def run_cycle(mcp_manager, llm):
    # ... existing handlers ...
    my_handler = MyHandler(mcp_manager, llm, WHATSAPP_NOTIFY_NUMBER)
    await my_handler.process()
```

## Adding a new MCP server

In `build_mcp_manager()` in `claude-agent.py`:

```python
manager.add_server("myserver", [
    "npx", "-y", "some-mcp-package",
], env={
    "SOME_ENV_VAR": "value",
})
```

Tool calls then use `myserver__tool_name` as the namespaced tool name.

## Examples of useful MCP servers

| Purpose | Package |
|---------|---------|
| Web search | `@modelcontextprotocol/server-brave-search` |
| Filesystem | `@modelcontextprotocol/server-filesystem` |
| Slack | `@modelcontextprotocol/server-slack` |
| GitHub | `@modelcontextprotocol/server-github` |
| Web browsing | `@playwright/mcp` (already supported, set `ENABLE_PLAYWRIGHT=true`) |

See the [MCP server registry](https://github.com/modelcontextprotocol/servers) for more.

## Action type naming convention

Use snake_case: `send_email`, `create_calendar_event`, `slack_message`, etc.

Keep action payloads serializable to JSON (no Python objects).
