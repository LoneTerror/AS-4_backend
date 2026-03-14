"""
Slack notification sender — Aabhar enterprise edition.

All messages are structured using Slack Block Kit.
No emojis. Professional tone consistent with HDFC-style brand standards.

Requires scopes: chat:write, im:write, users:read.email
"""

import logging
import os
from dataclasses import dataclass

from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)


# ── Brand colours (referenced in Block Kit where supported) ───────────────────
_RED   = "#E31837"
_NAVY  = "#004C8F"

# Per-type sidebar colour (attachment fallback colour strip)
_TYPE_COLOR = {
    "REVIEW":       _NAVY,
    "REWARD":       _RED,
    "SYSTEM":       "#374151",
    "CELEBRATION":  _RED,
    "ANNOUNCEMENT": _NAVY,
}

# Per-type display label
_TYPE_LABEL = {
    "REVIEW":       "Performance Review",
    "REWARD":       "Reward and Recognition",
    "SYSTEM":       "System Notice",
    "CELEBRATION":  "Recognition and Celebration",
    "ANNOUNCEMENT": "Company Announcement",
}

# Teasers for private notification types — do not expose content in Slack
_TYPE_TEASER = {
    "REVIEW": (
        "A new performance review has been submitted for your record. "
        "Please log in to the Aabhar HR Platform to access the full details."
    ),
    "REWARD": (
        "A reward has been issued to your account. "
        "Please log in to the Aabhar HR Platform to view the details."
    ),
}


# ── Config ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SlackConfig:
    bot_token: str
    default_channel_id: str

    @classmethod
    def from_env(cls) -> "SlackConfig":
        return cls(
            bot_token=os.environ["SLACK_BOT_TOKEN"],
            default_channel_id=os.environ["SLACK_DEFAULT_CHANNEL_ID"],
        )


# ── Sender ────────────────────────────────────────────────────────────────────

class SlackSender:
    def __init__(self, config: SlackConfig) -> None:
        self._cfg = config
        self._client = AsyncWebClient(token=config.bot_token)

    async def get_user_id_by_email(self, email: str) -> str | None:
        """
        Resolve a Slack user ID from a work email address.
        Returns None if the user is not found in the workspace.
        Requires scope: users:read.email
        """
        try:
            resp = await self._client.users_lookupByEmail(email=email)
            return resp["user"]["id"]
        except SlackApiError as e:
            if e.response.get("error") == "users_not_found":
                logger.debug("Slack: no user found for email %s", email)
                return None
            logger.warning(
                "Slack: user lookup failed for %s — %s", email, e.response.get("error")
            )
            return None

    async def send_dm(
        self,
        *,
        slack_user_id: str,
        title: str,
        message: str,
        type_: str,
    ) -> None:
        """
        Send a direct message to a specific Slack user.

        Used for REVIEW, REWARD, and SYSTEM notifications — always personal,
        never posted to a public channel. Does not fall back to the default
        channel; if the user ID is invalid the error propagates to the caller.

        Requires scopes: chat:write, im:write
        """
        blocks, fallback = _build_notification_blocks(
            title=title, message=message, type_=type_
        )
        await self._client.chat_postMessage(
            channel=slack_user_id,
            text=fallback,
            blocks=blocks,
        )
        logger.info("Slack DM sent to user %s | type=%s title=%r", slack_user_id, type_, title)

    async def send_notification(
        self,
        *,
        slack_user_id: str | None,
        title: str,
        message: str,
        type_: str,
    ) -> None:
        """
        Send to user DM if their Slack ID is known; fall back to default channel.
        Retained for backwards compatibility — prefer send_dm for personal notifications.
        Requires scopes: chat:write, im:write
        """
        channel = slack_user_id or self._cfg.default_channel_id
        blocks, fallback = _build_notification_blocks(
            title=title, message=message, type_=type_
        )
        await self._client.chat_postMessage(
            channel=channel,
            text=fallback,
            blocks=blocks,
        )
        logger.info(
            "Slack notification sent to %s | type=%s title=%r", channel, type_, title
        )

    async def send_celebration(
        self,
        *,
        channel_id: str | None,
        employee_name: str,
        celebration_type: str,
        years: int | None = None,
    ) -> None:
        """
        Post a celebration announcement to the default public channel.
        Always public — never sent as a DM.
        Requires scope: chat:write
        """
        blocks, fallback = _build_celebration_blocks(
            employee_name=employee_name,
            celebration_type=celebration_type,
            years=years,
        )
        channel = self._cfg.default_channel_id
        await self._client.chat_postMessage(
            channel=channel,
            text=fallback,
            blocks=blocks,
        )
        logger.info(
            "Slack celebration posted to channel %s | type=%s employee=%s",
            channel, celebration_type, employee_name,
        )


# ── Block Kit: notification (REVIEW / REWARD / SYSTEM / ANNOUNCEMENT) ─────────

def _build_notification_blocks(
    *, title: str, message: str, type_: str
) -> tuple[list[dict], str]:
    """
    Returns (blocks, fallback_text).

    For REVIEW and REWARD, body content is suppressed in favour of a
    generic teaser — the full notification lives in email and in-app only.
    """
    label   = _TYPE_LABEL.get(type_, type_.replace("_", " ").title())
    color   = _TYPE_COLOR.get(type_, _NAVY)
    teaser  = _TYPE_TEASER.get(type_)
    body    = teaser if teaser else message
    display = teaser if teaser else title

    # Fallback plain text (shown in push notifications and older clients)
    fallback = f"[{label}] {display}"

    blocks: list[dict] = [
        # ── Type label + horizontal rule visual via context ────────────────
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"*AABHAR HR PLATFORM*   |   {label.upper()}",
                }
            ],
        },
        {"type": "divider"},

        # ── Title ──────────────────────────────────────────────────────────
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": display if teaser else title,
                "emoji": False,
            },
        },

        # ── Body ───────────────────────────────────────────────────────────
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": body,
            },
        },

        {"type": "divider"},

        # ── Action prompt ──────────────────────────────────────────────────
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    "Please log in to the *Aabhar HR Platform* to view the complete "
                    "details of this notification and take any required action."
                ),
            },
        },

        # ── Footer metadata ────────────────────────────────────────────────
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        "This is an automated system notification from Aabhar HR Platform. "
                        "Please do not reply to this message. "
                        "For queries, contact your HR representative."
                    ),
                }
            ],
        },
    ]

    return blocks, fallback


# ── Block Kit: celebration (BIRTHDAY / WORK_ANNIVERSARY) ──────────────────────

def _build_celebration_blocks(
    *,
    employee_name: str,
    celebration_type: str,
    years: int | None = None,
) -> tuple[list[dict], str]:
    """
    Returns (blocks, fallback_text) for a public channel celebration post.
    """
    if celebration_type == "BIRTHDAY":
        headline      = f"Birthday Announcement — {employee_name}"
        subheading    = "Today marks the birthday of one of our colleagues."
        body          = (
            f"Please join us in extending warm birthday wishes to *{employee_name}*. "
            f"We appreciate the dedication and effort that {employee_name.split()[0]} "
            f"brings to the team each day. "
            f"We hope this year ahead is one of good health, growth, and personal fulfilment."
        )
        call_to_action = (
            f"We encourage all team members to reach out directly to {employee_name.split()[0]} "
            f"with a personal message of acknowledgement."
        )
        label         = "Birthday Recognition"
    else:  # WORK_ANNIVERSARY
        ordinal       = _ordinal(years)
        yr_word       = f"{years} year{'s' if (years or 0) != 1 else ''}"
        headline      = f"Work Anniversary — {employee_name} | {ordinal} Year"
        subheading    = f"A significant professional milestone: {yr_word} of service with Aabhar."
        body          = (
            f"We are pleased to recognise *{employee_name}* on the occasion of their "
            f"*{ordinal} work anniversary* with Aabhar. "
            f"This milestone is a testament to consistent dedication, professionalism, "
            f"and the ongoing contribution that {employee_name.split()[0]} makes to our organisation. "
            f"Sustained commitment of this nature strengthens the culture and capability of the "
            f"entire team, and it deserves to be formally acknowledged."
        )
        call_to_action = (
            f"We invite all colleagues to take a moment to congratulate "
            f"{employee_name.split()[0]} on this distinguished anniversary."
        )
        label         = "Work Anniversary"

    fallback = f"[{label}] {headline}"

    blocks: list[dict] = [
        # ── Platform header ────────────────────────────────────────────────
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"*AABHAR HR PLATFORM*   |   {label.upper()}",
                }
            ],
        },
        {"type": "divider"},

        # ── Headline ───────────────────────────────────────────────────────
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": headline,
                "emoji": False,
            },
        },

        # ── Subheading ─────────────────────────────────────────────────────
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"_{subheading}_",
            },
        },

        {"type": "divider"},

        # ── Body ───────────────────────────────────────────────────────────
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": body,
            },
        },

        # ── Call to action ─────────────────────────────────────────────────
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": call_to_action,
            },
        },

        {"type": "divider"},

        # ── Footer ─────────────────────────────────────────────────────────
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        "This announcement has been issued by the Aabhar HR Platform "
                        "on behalf of the People and Culture team. "
                        "This is an automated message."
                    ),
                }
            ],
        },
    ]

    return blocks, fallback


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ordinal(n: int | None) -> str:
    if n is None:
        return ""
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(
        n % 10 if n % 100 not in (11, 12, 13) else 0, "th"
    )
    return f"{n}{suffix}"