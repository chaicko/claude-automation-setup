# Claude Code Rules — claude-automation-setup

## Project Overview
Background autonomous agent that monitors Gmail/Calendar, uses WhatsApp for approvals, and runs on a home server with Ollama (local LLM).

## Key Architecture Decisions
- **LLM**: Ollama (qwen2.5:7b) by default. Anthropic API is optional fallback via `MODEL_PROVIDER=anthropic`.
- **Approval channel**: WhatsApp only. Ale replies YES/NO/EDIT to authorize actions.
- **MCP servers**: subprocess JSON-RPC (no Anthropic SDK required for the daemon).
- **State**: Pending actions in `data/pending.json`. Audit log in `data/actions.log`.

## File Map
- `agent/claude-agent.py` — main entrypoint, cycle orchestration
- `agent/mcp_client.py` — MCP subprocess manager + tool executor
- `agent/llm_client.py` — Ollama/Anthropic unified client
- `agent/approval_loop.py` — WhatsApp approval state machine
- `agent/handlers/email_handler.py` — Gmail polling + draft generation
- `agent/handlers/calendar_handler.py` — Calendar polling + briefings

## Coding Rules
- All async (asyncio). No sync blocking calls in agent code.
- Tool names are namespaced: `server__tool` (double underscore).
- Never commit `.env` or `data/`. Always use `.env.example` for templates.
- Log generously at INFO level. Use DEBUG for noisy details.
- JSON-parse LLM responses defensively (regex fallback).

## Adding New Handlers
1. Create `agent/handlers/my_handler.py` with a class + `async def process()` method.
2. Import and call it in `claude-agent.py`'s `run_cycle()`.
3. If it needs a new MCP server, add it in `build_mcp_manager()`.

## Testing Without Home Server
Set `MODEL_PROVIDER=anthropic` and `ANTHROPIC_API_KEY=...` in `.env` to use Claude API on the dev laptop. MCP servers still need to be running (use `claude mcp add` or `npx` manually).

## Do NOT
- Do not add dependencies beyond `openai`, `python-dotenv`, `mcp`.
- Do not store secrets in code. Always read from environment.
- Do not add synchronous HTTP calls in the agent event loop.
