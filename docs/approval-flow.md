# Approval Flow

## How the WhatsApp loop works

Every agent cycle:

1. **Detect action** — agent finds an email needing a reply, or a calendar event to create
2. **Draft** — Ollama (or Anthropic) generates a draft
3. **Notify** — agent sends you a WhatsApp message:

   ```
   📧 Email from João <joao@example.com>
   Subject: Invoice #1234

   Draft reply:
   Hi João, thanks for the invoice. I'll review and process by Friday.

   Reply YES abc123 / NO abc123 / EDIT <your text> abc123
   ```

4. **Pending** — action is saved to `data/pending.json` with a 24h expiry
5. **Next cycle** — agent reads your recent WhatsApp messages and processes replies

## Reply commands

| Your reply | Effect |
|-----------|--------|
| `YES abc123` | Execute the action (send email, create event, etc.) |
| `NO abc123` | Discard the action, log it as rejected |
| `EDIT Hi João, I'll get back to you next week abc123` | Update the draft with your text, re-send for confirmation |

The action ID (`abc123`) is an 8-character hex string included in every notification. You can also reply with just `YES`, `NO`, or `EDIT <text>` without the ID if there's only one pending action — the agent will try to match it.

## Confirmation messages

After execution:
- ✅ `Done [abc123]: Email sent` — action succeeded
- ❌ `Failed [abc123]: <error>` — action failed (check `data/actions.log`)
- 🗑 `Discarded [abc123]` — you said NO

## Expiry

Pending actions expire after `APPROVAL_EXPIRY_HOURS` (default: 24 hours). Expired actions are logged but not executed. You'll see a notification if an action expires without a reply.

## State file

`data/pending.json` contains all pending actions:

```json
{
  "abc123": {
    "id": "abc123",
    "type": "send_email",
    "payload": {
      "to": "joao@example.com",
      "subject": "Re: Invoice #1234",
      "body": "Hi João, I'll review by Friday.",
      "replyToMessageId": "msg_xyz"
    },
    "expires_at": "2025-01-02T15:00:00+00:00",
    "status": "pending",
    "created_at": "2025-01-01T15:00:00+00:00"
  }
}
```

## Audit log

Every action (approved, rejected, expired, failed) is appended to `data/actions.log` as newline-delimited JSON.
