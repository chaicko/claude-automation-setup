#!/usr/bin/env python3
"""
Claude Automation Agent — main daemon.

Runs on a schedule (systemd timer or Docker entrypoint loop).
Polls Gmail + Calendar, drafts actions, requests WhatsApp approval from Ale,
and executes approved actions.

Usage:
  python claude-agent.py            # single run (for systemd timer)
  python claude-agent.py --loop     # continuous loop (for Docker)
  python claude-agent.py --setup    # one-time OAuth/QR setup
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from mcp_client import MCPManager
from llm_client import LLMClient
from approval_loop import get_pending_actions, process_approval, parse_whatsapp_reply
from handlers.email_handler import EmailHandler
from handlers.calendar_handler import CalendarHandler

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            Path(os.getenv("DATA_DIR", "data")) / "agent.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("claude-agent")

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
load_dotenv()

WHATSAPP_NOTIFY_NUMBER = os.getenv("WHATSAPP_NOTIFY_NUMBER", "")
DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", str(15 * 60)))


# ---------------------------------------------------------------------------
# MCP server configuration
# ---------------------------------------------------------------------------

def build_mcp_manager() -> MCPManager:
    manager = MCPManager()

    # WhatsApp MCP (Go binary from lharries/whatsapp-mcp)
    whatsapp_bin = os.getenv("WHATSAPP_MCP_BIN", str(Path.home() / ".local/bin/whatsapp-mcp"))
    if Path(whatsapp_bin).exists():
        manager.add_server("whatsapp", [whatsapp_bin], env={
            "WHATSAPP_DB_PATH": str(DATA_DIR / "whatsapp" / "whatsapp.db"),
        })
    else:
        logger.warning(f"WhatsApp MCP binary not found at {whatsapp_bin}. Skipping.")

    # Gmail MCP
    gmail_token_dir = str(DATA_DIR / "gmail")
    manager.add_server("gmail", [
        "npx", "-y", "@modelcontextprotocol/server-gmail",
    ], env={
        "GMAIL_TOKEN_PATH": gmail_token_dir,
    })

    # Google Calendar MCP
    calendar_token_dir = str(DATA_DIR / "calendar")
    manager.add_server("calendar", [
        "npx", "-y", "@cocal/google-calendar-mcp",
    ], env={
        "GOOGLE_CALENDAR_TOKEN_PATH": calendar_token_dir,
    })

    # Playwright MCP (optional, for web tasks)
    if os.getenv("ENABLE_PLAYWRIGHT", "false").lower() == "true":
        manager.add_server("playwright", [
            "npx", "@playwright/mcp@latest", "--headless",
        ])

    return manager


# ---------------------------------------------------------------------------
# Action executor (called by approval_loop on YES)
# ---------------------------------------------------------------------------

async def execute_action(action: dict, mcp_manager: MCPManager) -> str:
    """Execute an approved action."""
    action_type = action["type"]
    payload = action["payload"]

    if action_type == "send_email":
        result = await mcp_manager.execute_tool_call("gmail__send_email", payload)
        return f"Email sent: {result[:100]}"

    elif action_type == "create_calendar_event":
        result = await mcp_manager.execute_tool_call(
            "calendar__create_event", payload
        )
        return f"Event created: {result[:100]}"

    elif action_type == "send_email_edited":
        # Payload has edited_text replacing the body
        send_payload = {**payload, "body": payload.get("edited_text", payload.get("body", ""))}
        result = await mcp_manager.execute_tool_call("gmail__send_email", send_payload)
        return f"Edited email sent: {result[:100]}"

    else:
        raise ValueError(f"Unknown action type: '{action_type}'")


# ---------------------------------------------------------------------------
# Approval polling: read recent WhatsApp messages and process replies
# ---------------------------------------------------------------------------

async def poll_whatsapp_replies(mcp_manager: MCPManager, llm: LLMClient):
    """Read recent WhatsApp messages from Ale and process any approval replies."""
    if not WHATSAPP_NOTIFY_NUMBER:
        logger.debug("WHATSAPP_NOTIFY_NUMBER not set, skipping reply poll")
        return

    pending = get_pending_actions()
    if not pending:
        return

    logger.info(f"Checking WhatsApp replies ({len(pending)} pending actions)")

    try:
        # Get recent messages from Ale's number
        messages_json = await mcp_manager.execute_tool_call(
            "whatsapp__get_messages",
            {"phone": WHATSAPP_NOTIFY_NUMBER, "limit": 20},
        )
    except Exception as e:
        logger.error(f"Failed to fetch WhatsApp messages: {e}")
        return

    import json
    try:
        messages = json.loads(messages_json) if isinstance(messages_json, str) else messages_json
    except Exception:
        messages = []

    if not isinstance(messages, list):
        messages = []

    pending_ids = {a["id"] for a in pending}

    for msg in messages:
        text = msg.get("text", "") or msg.get("body", "") or msg.get("content", "")
        if not text:
            continue

        # Try to match this message to a pending action
        for action_id in pending_ids:
            parsed = parse_whatsapp_reply(text, action_id=action_id)
            if parsed and parsed.get("action_id") == action_id:
                logger.info(f"Matched reply '{parsed['command']}' for action {action_id}")
                await process_approval(
                    parsed,
                    executor=lambda a: execute_action(a, mcp_manager),
                    mcp_manager=mcp_manager,
                    notify_number=WHATSAPP_NOTIFY_NUMBER,
                )
                pending_ids.discard(action_id)
                break


# ---------------------------------------------------------------------------
# Main agent cycle
# ---------------------------------------------------------------------------

async def run_cycle(mcp_manager: MCPManager, llm: LLMClient):
    """One full agent cycle: process emails, calendar, and approval replies."""
    logger.info("--- Agent cycle start ---")

    email_handler = EmailHandler(mcp_manager, llm, WHATSAPP_NOTIFY_NUMBER)
    calendar_handler = CalendarHandler(mcp_manager, llm, WHATSAPP_NOTIFY_NUMBER)

    # Process pending WhatsApp replies first
    await poll_whatsapp_replies(mcp_manager, llm)

    # Check Gmail for new emails needing attention
    await email_handler.process()

    # Check calendar for upcoming events needing reminders
    await calendar_handler.process()

    logger.info("--- Agent cycle complete ---")


async def setup_mode():
    """Interactive setup: trigger OAuth flows and WhatsApp QR scan."""
    print("\n=== Claude Automation Agent — First-Time Setup ===\n")
    print("This will guide you through:")
    print("  1. Gmail OAuth authorization")
    print("  2. Google Calendar OAuth authorization")
    print("  3. WhatsApp QR code scan\n")

    manager = build_mcp_manager()
    print("Starting MCP servers for setup...")
    await manager.start_all()

    print("\n[Gmail] Check browser/terminal for OAuth prompt...")
    try:
        result = await manager.execute_tool_call("gmail__list_messages", {"maxResults": 1})
        print(f"  Gmail OK: {result[:80]}")
    except Exception as e:
        print(f"  Gmail setup may need manual intervention: {e}")

    print("\n[Calendar] Check browser/terminal for OAuth prompt...")
    try:
        result = await manager.execute_tool_call("calendar__list_events", {"maxResults": 1})
        print(f"  Calendar OK: {result[:80]}")
    except Exception as e:
        print(f"  Calendar setup may need manual intervention: {e}")

    print("\n[WhatsApp] Scan the QR code that appears below...")
    try:
        result = await manager.execute_tool_call("whatsapp__get_qr", {})
        print(result)
    except Exception as e:
        print(f"  WhatsApp setup: {e}")

    await manager.stop_all()
    print("\nSetup complete. You can now run the agent normally.")


async def main_async(args):
    if args.setup:
        await setup_mode()
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    mcp_manager = build_mcp_manager()
    await mcp_manager.start_all()

    llm = LLMClient()

    try:
        if args.loop:
            logger.info(f"Running in loop mode (interval={POLL_INTERVAL_SECONDS}s)")
            while True:
                try:
                    await run_cycle(mcp_manager, llm)
                except Exception as e:
                    logger.error(f"Cycle error: {e}", exc_info=True)
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
        else:
            await run_cycle(mcp_manager, llm)
    finally:
        await mcp_manager.stop_all()


def main():
    parser = argparse.ArgumentParser(description="Claude Automation Agent")
    parser.add_argument("--loop", action="store_true",
                        help="Run continuously (for Docker)")
    parser.add_argument("--setup", action="store_true",
                        help="Run one-time OAuth/QR setup")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
