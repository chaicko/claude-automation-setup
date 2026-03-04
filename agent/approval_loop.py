"""
WhatsApp approval state machine.

Manages pending actions that require human approval via WhatsApp.
Ale replies YES / NO / EDIT <text> to authorize actions.

State file: data/pending.json
"""

import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

PENDING_FILE = Path(os.getenv("DATA_DIR", "data")) / "pending.json"
ACTIONS_LOG = Path(os.getenv("DATA_DIR", "data")) / "actions.log"
DEFAULT_EXPIRY_HOURS = int(os.getenv("APPROVAL_EXPIRY_HOURS", "24"))


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _load_pending() -> dict:
    if PENDING_FILE.exists():
        try:
            return json.loads(PENDING_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_pending(pending: dict):
    PENDING_FILE.parent.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(json.dumps(pending, indent=2, default=str))


def _append_log(entry: dict):
    ACTIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with ACTIONS_LOG.open("a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def create_pending_action(
    action_type: str,
    payload: dict,
    whatsapp_message: str | Callable[[str], str],
    expiry_hours: int = DEFAULT_EXPIRY_HOURS,
) -> str:
    """
    Register a pending action awaiting approval.
    Returns the action ID to include in the WhatsApp message.

    whatsapp_message can be a plain string or a callable that receives the
    action_id and returns the message string. Use the callable form when the
    message needs to embed the action_id:

        create_pending_action(..., whatsapp_message=lambda aid: f"Reply YES {aid}")
    """
    action_id = str(uuid.uuid4())[:8]
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=expiry_hours)).isoformat()

    if callable(whatsapp_message):
        whatsapp_message = whatsapp_message(action_id)

    pending = _load_pending()
    pending[action_id] = {
        "id": action_id,
        "type": action_type,
        "payload": payload,
        "whatsapp_message": whatsapp_message,
        "expires_at": expires_at,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_pending(pending)
    logger.info(f"Created pending action {action_id} ({action_type})")
    return action_id


def get_pending_actions() -> list[dict]:
    """Return all non-expired pending actions."""
    pending = _load_pending()
    now = datetime.now(timezone.utc)
    active = []
    expired_ids = []

    for action_id, action in pending.items():
        if action["status"] != "pending":
            continue
        expires_at = datetime.fromisoformat(action["expires_at"])
        if expires_at < now:
            expired_ids.append(action_id)
        else:
            active.append(action)

    # Mark expired
    if expired_ids:
        for action_id in expired_ids:
            pending[action_id]["status"] = "expired"
            _append_log({"event": "expired", **pending[action_id]})
        _save_pending(pending)
        logger.info(f"Expired {len(expired_ids)} pending actions")

    return active


def parse_whatsapp_reply(text: str, action_id: str | None = None) -> dict | None:
    """
    Parse a WhatsApp reply from Ale.

    Expected formats (case-insensitive):
      YES [<id>]
      NO [<id>]
      EDIT <new text> [<id>]

    Returns dict with keys: command, action_id, edit_text (if EDIT)
    Returns None if text doesn't match any expected format.
    """
    text = text.strip()

    # Try to extract trailing action ID like "abc123" at end
    id_match = re.search(r'\b([a-f0-9]{8})\b', text)
    extracted_id = id_match.group(1) if id_match else action_id

    upper = text.upper()

    if upper.startswith("YES"):
        return {"command": "YES", "action_id": extracted_id}

    if upper.startswith("NO"):
        return {"command": "NO", "action_id": extracted_id}

    if upper.startswith("EDIT "):
        # Everything after "EDIT " (and optional ID) is the new text
        edit_text = re.sub(r'^EDIT\s+', '', text, flags=re.IGNORECASE)
        # Remove trailing action ID if present
        if extracted_id:
            edit_text = edit_text.replace(extracted_id, "").strip()
        return {"command": "EDIT", "action_id": extracted_id, "edit_text": edit_text}

    return None


async def process_approval(
    reply: dict,
    executor,  # async callable(action: dict) -> str
    mcp_manager,  # MCPManager instance for sending WhatsApp confirmations
    notify_number: str,
) -> None:
    """
    Process a parsed WhatsApp reply and execute or discard the action.
    """
    pending = _load_pending()
    action_id = reply.get("action_id")

    if not action_id or action_id not in pending:
        logger.warning(f"Reply references unknown action_id: {action_id}")
        return

    action = pending[action_id]
    if action["status"] != "pending":
        logger.info(f"Action {action_id} already {action['status']}, ignoring reply")
        return

    command = reply["command"]

    if command == "YES":
        try:
            result = await executor(action)
            action["status"] = "approved"
            _append_log({"event": "approved", "result": result, **action})
            await _whatsapp_send(mcp_manager, notify_number,
                                 f"✅ Done [{action_id}]: {result[:200]}")
            logger.info(f"Action {action_id} approved and executed")
        except Exception as e:
            action["status"] = "failed"
            _append_log({"event": "failed", "error": str(e), **action})
            await _whatsapp_send(mcp_manager, notify_number,
                                 f"❌ Failed [{action_id}]: {e}")
            logger.error(f"Action {action_id} execution failed: {e}")

    elif command == "NO":
        action["status"] = "rejected"
        _append_log({"event": "rejected", **action})
        await _whatsapp_send(mcp_manager, notify_number,
                             f"🗑 Discarded [{action_id}]")
        logger.info(f"Action {action_id} rejected")

    elif command == "EDIT":
        edit_text = reply.get("edit_text", "")
        action["payload"]["edited_text"] = edit_text
        # Re-send for confirmation with updated content
        new_message = (
            f"✏️ Updated draft [{action_id}]:\n"
            f"{edit_text}\n\n"
            f"Reply YES {action_id} / NO {action_id}"
        )
        await _whatsapp_send(mcp_manager, notify_number, new_message)
        logger.info(f"Action {action_id} updated with EDIT, re-sent for approval")
        # Keep status as "pending"

    _save_pending(pending)


async def _whatsapp_send(mcp_manager, number: str, message: str):
    """Send a WhatsApp message via the whatsapp MCP server."""
    try:
        await mcp_manager.execute_tool_call("whatsapp__send_message", {
            "phone": number,
            "message": message,
        })
    except Exception as e:
        logger.error(f"Failed to send WhatsApp message: {e}")
