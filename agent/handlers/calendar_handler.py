"""
Calendar handler: polls Google Calendar for upcoming events,
sends reminders/summaries via WhatsApp, and proposes new events.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone

from approval_loop import create_pending_action
from mcp_client import MCPManager
from llm_client import LLMClient

logger = logging.getLogger(__name__)

REMINDER_SYSTEM_PROMPT = """You are a calendar assistant for Ale.
Given a list of upcoming calendar events, generate a concise daily briefing.

Format:
- List events for today and tomorrow only
- Include time, title, and location (if any)
- Flag any conflicts
- Keep it under 200 words
- Use a friendly, conversational tone

Respond with plain text (no JSON needed)."""

LOOKAHEAD_HOURS = int(os.getenv("CALENDAR_LOOKAHEAD_HOURS", "24"))


class CalendarHandler:
    def __init__(self, mcp_manager: MCPManager, llm: LLMClient, notify_number: str):
        self.mcp = mcp_manager
        self.llm = llm
        self.notify_number = notify_number
        self._already_reminded: set[str] = set()

    async def process(self):
        """Fetch upcoming events and send WhatsApp reminder if needed."""
        logger.info("Checking Google Calendar...")

        now = datetime.now(timezone.utc)
        time_max = now + timedelta(hours=LOOKAHEAD_HOURS)

        try:
            raw = await self.mcp.execute_tool_call("calendar__list_events", {
                "timeMin": now.isoformat(),
                "timeMax": time_max.isoformat(),
                "maxResults": 20,
                "singleEvents": True,
                "orderBy": "startTime",
            })
        except Exception as e:
            logger.error(f"Failed to fetch calendar events: {e}")
            return

        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            events = data.get("items", data) if isinstance(data, dict) else data
        except Exception:
            events = []

        if not events:
            logger.info("No upcoming events in the next 24 hours")
            return

        logger.info(f"Found {len(events)} upcoming event(s)")
        await self._send_daily_briefing(events)

    async def _send_daily_briefing(self, events: list[dict]):
        """Generate and send a daily briefing via WhatsApp."""
        if not self.notify_number:
            return

        # Format events for LLM
        events_text = self._format_events(events)

        response = await self.llm.run_agent_loop(
            system_prompt=REMINDER_SYSTEM_PROMPT,
            user_message=f"Upcoming events:\n\n{events_text}",
            tools=[],
            tool_executor=self.mcp.execute_tool_call,
        )

        briefing = f"📅 Calendar Briefing\n\n{response}"

        try:
            await self.mcp.execute_tool_call("whatsapp__send_message", {
                "phone": self.notify_number,
                "message": briefing,
            })
            logger.info("Sent calendar briefing via WhatsApp")
        except Exception as e:
            logger.error(f"Failed to send calendar briefing: {e}")

    async def propose_event(
        self,
        title: str,
        description: str,
        start_time: str,
        end_time: str,
        attendees: list[str] | None = None,
    ) -> str:
        """
        Propose creating a calendar event; requires WhatsApp approval.
        Returns the action_id.
        """
        payload = {
            "summary": title,
            "description": description,
            "start": {"dateTime": start_time},
            "end": {"dateTime": end_time},
        }
        if attendees:
            payload["attendees"] = [{"email": e} for e in attendees]

        action_id = create_pending_action(
            action_type="create_calendar_event",
            payload=payload,
            whatsapp_message=lambda aid: (
                f"📅 Create event: {title}\n"
                f"🕐 {start_time} → {end_time}\n"
                f"{description}\n\n"
                f"Reply YES {aid} / NO {aid}"
            ),
        )

        if self.notify_number:
            try:
                await self.mcp.execute_tool_call("whatsapp__send_message", {
                    "phone": self.notify_number,
                    "message": (
                        f"📅 Create event: {title}\n"
                        f"🕐 {start_time} → {end_time}\n"
                        f"{description}\n\n"
                        f"Reply YES {action_id} / NO {action_id}"
                    ),
                })
            except Exception as e:
                logger.error(f"Failed to send WhatsApp event proposal: {e}")

        return action_id

    def _format_events(self, events: list[dict]) -> str:
        lines = []
        for event in events:
            start = event.get("start", {})
            start_str = start.get("dateTime", start.get("date", "unknown"))
            title = event.get("summary", "(no title)")
            location = event.get("location", "")
            loc_str = f" @ {location}" if location else ""
            lines.append(f"- {start_str}: {title}{loc_str}")
        return "\n".join(lines)
