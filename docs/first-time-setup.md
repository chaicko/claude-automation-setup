# First-Time Setup

## 1. Clone and configure

```bash
git clone https://github.com/chaicko/claude-automation-setup.git
cd claude-automation-setup
cp .env.example .env
```

Edit `.env` — at minimum set `WHATSAPP_NOTIFY_NUMBER` to your WhatsApp number in international format (e.g. `+541112345678`).

## 2. Gmail OAuth

The Gmail MCP server (`@modelcontextprotocol/server-gmail`) uses OAuth 2.0.

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → Enable **Gmail API**
3. Create **OAuth 2.0 credentials** (Desktop app type)
4. Download `credentials.json` → place at `data/gmail/credentials.json`

When you run `setup.sh --auth` or `docker compose run agent --setup`, the agent will open a browser URL for you to authorize. The resulting token is saved to `data/gmail/token.json`.

## 3. Google Calendar OAuth

Same process as Gmail:

1. In the same Google Cloud project → Enable **Google Calendar API**
2. The same `credentials.json` works for both Gmail and Calendar
3. Copy it to `data/calendar/credentials.json` as well (or symlink)

The Calendar MCP (`@cocal/google-calendar-mcp`) will prompt for authorization on first run. Token saved to `data/calendar/token.json`.

## 4. WhatsApp QR Scan

The WhatsApp MCP uses the WhatsApp multi-device protocol (via `lharries/whatsapp-mcp`).

1. Run setup: `bash setup.sh --auth`
2. A QR code appears in the terminal
3. On your phone: WhatsApp → Linked Devices → Link a Device → scan the QR
4. Session is saved to `data/whatsapp/whatsapp.db` — no need to scan again

**Important**: The QR code expires quickly. Be ready to scan immediately.

## 5. Start the agent

**Bare metal:**
```bash
systemctl --user start claude-agent.timer
systemctl --user status claude-agent.timer
journalctl --user -u claude-agent -f
```

**Docker:**
```bash
docker compose up -d
docker compose logs -f agent
```

## Verifying everything works

Send yourself a test email and wait up to 15 minutes (one agent cycle). You should receive a WhatsApp message with a draft reply and `YES/NO/EDIT` options.

Check `data/agent.log` for detailed cycle logs.
