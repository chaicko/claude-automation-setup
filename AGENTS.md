# Agent Instructions — claude-automation-setup

## What this repo is

A background autonomous agent that monitors Gmail and Google Calendar, drafts
responses using a local LLM (Ollama / Qwen 2.5 7B), and routes all actions
through a WhatsApp approval loop before executing them. Runs on a home server
via systemd or Docker. Also ships a NixOS flake for declarative deployment.

## Code review priorities

When reviewing PRs, focus on these areas in order of importance:

### 1. Correctness of the approval loop (`agent/approval_loop.py`)
This is the safety-critical path. Every action that touches Gmail or Calendar
must go through `create_pending_action` → WhatsApp reply → `process_approval`.
Flag anything that:
- Executes a side-effecting action (send email, create event) without a prior
  approval check
- Allows `status != "pending"` actions to be re-executed
- Has race conditions in `_load_pending` / `_save_pending` (file-based locking
  is not implemented; flag if concurrent writes become possible)
- Lets expired actions execute

### 2. MCP tool call safety (`agent/mcp_client.py`)
- Tool names must be namespaced as `server__tool` (double underscore). Flag
  any direct tool name without a namespace.
- `execute_tool_call` must never swallow exceptions silently — errors must
  propagate to the caller or be logged at ERROR level.
- Check that subprocess stdout is read before stdin is closed (deadlock risk
  in `_send_request`).

### 3. LLM response parsing (`agent/handlers/`)
- LLM output is untrusted. Any JSON parsed from an LLM response must have a
  defensive fallback (try/except + regex extraction). Flag bare `json.loads`
  on LLM output without error handling.
- Prompt injections via email body content: the email body is included in the
  LLM prompt. Flag any handler that passes raw email body to the LLM without
  length-capping or sanitisation.

### 4. Secrets hygiene
- No secrets, tokens, or credentials in code or committed files.
- `.env` and `data/` are gitignored — flag any PR that adds files under
  `data/` or a literal `.env`.
- NixOS: `envFile` must point outside the Nix store (store paths are world-
  readable). Flag any hardcoded `/nix/store/...` path as an `envFile` value.

### 5. Nix correctness (`nix/`)
- Hashes in `whatsapp-mcp.nix` and `python-env.nix` must not be
  `lib.fakeHash` or the all-`A` placeholder in a non-draft PR.
- `nix/module.nix` options must have `description` and sensible `default`.
- Systemd units declared in the module must have `after`/`requires` on
  `ollama.service` — the agent must not start before the LLM is ready.

## What to ignore

- Style nits (formatting, variable naming) — no formatter is enforced yet.
- Missing docstrings on private helpers.
- The `setup.sh` script targets Fedora/Ubuntu/Debian and intentionally does
  not support NixOS — do not suggest making it NixOS-compatible.

## Architecture constraints

- **All agent code is async** (`asyncio`). Do not suggest sync alternatives.
- **No new Python dependencies** beyond `openai`, `python-dotenv`, `mcp`
  unless the PR explicitly justifies it.
- **No framework magic** — MCP tool calls are plain JSON-RPC over subprocess
  stdin/stdout. Do not suggest replacing this with an MCP SDK wrapper.
- The LLM client (`agent/llm_client.py`) must stay provider-agnostic:
  both Ollama and Anthropic use the same OpenAI-compatible call path.

## Test baseline

There are no automated tests yet. When reviewing logic changes, suggest a
minimal unit test for the changed function if one does not exist, but do not
block the PR on test absence.
