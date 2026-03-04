"""
Email handler: polls Gmail for unread emails needing attention,
drafts replies using the LLM, and sends WhatsApp approval requests.
"""

import json
import logging
import os
from datetime import datetime, timezone

from approval_loop import create_pending_action
from mcp_client import MCPManager
from llm_client import LLMClient

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an email assistant for Ale. Your job is to:
1. Read an incoming email
2. Decide if it needs a reply (skip newsletters, automated notifications, receipts)
3. If it needs a reply, draft a concise, professional response in the same language as the email

Always respond with valid JSON in this exact format:
{
  "needs_reply": true or false,
  "reason": "brief explanation",
  "draft_reply": "the draft email body (empty string if needs_reply is false)",
  "subject": "Re: original subject",
  "to": "sender email address"
}

Keep drafts under 150 words. Be direct and professional."""


class EmailHandler:
    def __init__(self, mcp_manager: MCPManager, llm: LLMClient, notify_number: str):
        self.mcp = mcp_manager
        self.llm = llm
        self.notify_number = notify_number
        self.max_emails_per_cycle = int(os.getenv("MAX_EMAILS_PER_CYCLE", "5"))

    async def process(self):
        """Check Gmail for unread emails and draft replies."""
        logger.info("Checking Gmail for new emails...")

        try:
            raw = await self.mcp.execute_tool_call("gmail__search_messages", {
                "q": "is:unread -label:automated -label:newsletters",
                "maxResults": self.max_emails_per_cycle,
            })
        except Exception as e:
            logger.error(f"Failed to fetch emails: {e}")
            return

        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            messages = data.get("messages", data) if isinstance(data, dict) else data
        except Exception:
            messages = []

        if not messages:
            logger.info("No unread emails requiring attention")
            return

        logger.info(f"Found {len(messages)} unread email(s)")

        for msg in messages:
            msg_id = msg.get("id") or msg.get("messageId")
            if not msg_id:
                continue
            await self._process_single_email(msg_id)

    async def _process_single_email(self, message_id: str):
        """Process a single email: draft a reply and queue for WhatsApp approval."""
        try:
            raw = await self.mcp.execute_tool_call("gmail__read_message", {
                "messageId": message_id,
            })
        except Exception as e:
            logger.error(f"Failed to read email {message_id}: {e}")
            return

        try:
            email_data = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            email_data = {"body": str(raw)}

        # Extract readable fields
        subject = email_data.get("subject", "(no subject)")
        sender = email_data.get("from", email_data.get("sender", "unknown"))
        body = email_data.get("body", email_data.get("snippet", ""))[:1000]

        email_summary = f"From: {sender}\nSubject: {subject}\n\nBody:\n{body}"

        logger.info(f"Analyzing email from {sender}: {subject}")

        # Ask LLM to decide and draft
        tools = self.mcp.all_tools_openai_format()
        response = await self.llm.run_agent_loop(
            system_prompt=SYSTEM_PROMPT,
            user_message=f"Analyze this email and draft a reply if needed:\n\n{email_summary}",
            tools=[],  # No tools needed for draft generation
            tool_executor=self.mcp.execute_tool_call,
        )

        try:
            result = json.loads(response)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            import re
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                try:
                    result = json.loads(match.group())
                except Exception:
                    logger.warning(f"Could not parse LLM response for email {message_id}")
                    return
            else:
                logger.warning(f"No JSON in LLM response for email {message_id}")
                return

        if not result.get("needs_reply"):
            logger.info(f"Email from {sender} does not need a reply: {result.get('reason')}")
            # Mark as read to avoid re-processing
            try:
                await self.mcp.execute_tool_call("gmail__modify_message", {
                    "messageId": message_id,
                    "removeLabelIds": ["UNREAD"],
                })
            except Exception:
                pass
            return

        draft = result.get("draft_reply", "")
        reply_subject = result.get("subject", f"Re: {subject}")
        reply_to = result.get("to", sender)

        if not draft:
            logger.warning(f"LLM said reply needed but no draft for email {message_id}")
            return

        # Create pending action
        action_id = create_pending_action(
            action_type="send_email",
            payload={
                "to": reply_to,
                "subject": reply_subject,
                "body": draft,
                "replyToMessageId": message_id,
            },
            whatsapp_message=(
                f"📧 Email from {sender}\n"
                f"Subject: {subject}\n\n"
                f"Draft reply:\n{draft}\n\n"
                f"Reply YES {action_id} / NO {action_id} / EDIT <text> {action_id}"
            ),
        )

        # Send WhatsApp notification
        if self.notify_number:
            try:
                await self.mcp.execute_tool_call("whatsapp__send_message", {
                    "phone": self.notify_number,
                    "message": (
                        f"📧 Email from {sender}\n"
                        f"Subject: {subject}\n\n"
                        f"Draft reply:\n{draft}\n\n"
                        f"Reply YES {action_id} / NO {action_id} / EDIT <text> {action_id}"
                    ),
                })
                logger.info(f"Sent WhatsApp approval request for action {action_id}")
            except Exception as e:
                logger.error(f"Failed to send WhatsApp notification: {e}")
