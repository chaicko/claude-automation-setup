# Claude Automation Agent

Background autonomous agent that monitors Gmail/Calendar, drafts responses using a **local LLM (Ollama)**, and messages you on **WhatsApp** when it needs approval.

```
You ← WhatsApp ← Home Server (Ollama + agent) → Gmail / Calendar
```

Reply **YES** / **NO** / **EDIT \<text\>** to approve or reject any action.

---

## Prerequisites

**Home server** (where the agent runs):
- Linux (NixOS, Fedora, Ubuntu, or Debian)
- NVIDIA GPU with ≥6GB VRAM (GTX 1060 or better) — for Ollama local inference
- Internet access for Gmail/Calendar OAuth

**Dev laptop** (optional):
- `MODEL_PROVIDER=anthropic` + `ANTHROPIC_API_KEY` to test without Ollama

---

## Quick Start

### Option A — NixOS flake (recommended for NixOS)

```nix
# In your server's flake.nix inputs:
claude-agent.url = "github:chaicko/claude-automation-setup";

# In your nixosConfigurations modules:
claude-agent.nixosModules.default
{ services.claude-agent.enable = true;
  services.claude-agent.envFile = "/etc/claude-agent/env"; }
```

Full instructions: [docs/nixos-setup.md](docs/nixos-setup.md)

### Option C — Docker Compose

```bash
git clone https://github.com/chaicko/claude-automation-setup.git
cd claude-automation-setup
cp .env.example .env
# Edit .env — set WHATSAPP_NOTIFY_NUMBER at minimum

# First-time setup: OAuth flows + WhatsApp QR scan
docker compose run --rm agent --setup

# Start everything
docker compose up -d
```

### Option D — Bare metal (Fedora/Ubuntu/Debian)

```bash
git clone https://github.com/chaicko/claude-automation-setup.git
cd claude-automation-setup
cp .env.example .env
# Edit .env

bash setup.sh            # installs Ollama, Node.js, Python deps, systemd timer
bash setup.sh --auth     # OAuth + WhatsApp QR scan (one-time)

systemctl --user start claude-agent.timer
```

---

## How It Works

1. **Agent runs every 15 minutes** (systemd timer or Docker loop)
2. Polls Gmail for unread emails → drafts a reply → sends WhatsApp:
   ```
   📧 Email from João re: invoice
   Draft: "Thanks, I'll review by Friday."
   Reply YES abc123 / NO abc123 / EDIT <your text> abc123
   ```
3. Polls Calendar → sends daily briefing of upcoming events
4. Reads your WhatsApp replies → executes approved actions → confirms

---

## Configuration

All config in `.env` (copy from `.env.example`):

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL_PROVIDER` | `ollama` | `ollama` or `anthropic` |
| `OLLAMA_MODEL` | `qwen2.5:7b` | Model name for Ollama |
| `ANTHROPIC_API_KEY` | — | Required if `MODEL_PROVIDER=anthropic` |
| `WHATSAPP_NOTIFY_NUMBER` | — | Your WhatsApp number (+54...) |
| `APPROVAL_EXPIRY_HOURS` | `24` | Hours before pending action expires |
| `MAX_EMAILS_PER_CYCLE` | `5` | Max emails processed per cycle |
| `ENABLE_PLAYWRIGHT` | `false` | Enable Playwright MCP for web tasks |

---

## Logs and State

| File | Contents |
|------|----------|
| `data/agent.log` | Agent cycle logs |
| `data/actions.log` | Audit log of all approved/rejected/expired actions |
| `data/pending.json` | Pending actions awaiting WhatsApp approval |

---

## Docs

- [NixOS setup](docs/nixos-setup.md) — Flake module, NVIDIA drivers, OAuth on NixOS
- [First-time setup](docs/first-time-setup.md) — OAuth flows, WhatsApp QR scan (non-NixOS)
- [Approval flow](docs/approval-flow.md) — How YES/NO/EDIT works in detail
- [Local vs cloud LLM](docs/local-vs-cloud-llm.md) — Ollama vs Anthropic API
- [Adding capabilities](docs/adding-capabilities.md) — How to add new handlers

---

## Security

- `.env` and `data/` are gitignored — never committed
- OAuth tokens stored locally in `data/gmail/` and `data/calendar/`
- WhatsApp session in `data/whatsapp/` (one-time QR scan per machine)
- All actions require explicit human approval before execution
