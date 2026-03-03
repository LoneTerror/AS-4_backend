import logging
import os
from dataclasses import dataclass

from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)


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


class SlackSender:
    def __init__(self, config: SlackConfig) -> None:
        self._cfg = config
        self._client = AsyncWebClient(token=config.bot_token)

    async def get_user_id_by_email(self, email: str) -> str | None:
        """
        Look up a Slack user by their work email.
        Returns None if not found.
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
                "Slack: lookup failed for %s — %s", email, e.response.get("error")
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
        Used for REVIEW, REWARD, SYSTEM notifications — personal, never public.
        Requires scopes: chat:write, im:write

        Unlike send_notification, this method does NOT fall back to the
        default channel. If the user ID is invalid the error propagates
        to the caller to log and skip.
        """
        blocks = _build_notification_blocks(title=title, message=message, type_=type_)
        await self._client.chat_postMessage(
            channel=slack_user_id,   # Slack opens a DM when channel = user ID
            text=f"{_TYPE_EMOJI.get(type_, '🔔')} {title}",
            blocks=blocks,
        )
        logger.info("Slack DM sent to user %s | title=%r", slack_user_id, title)

    async def send_notification(
        self,
        *,
        slack_user_id: str | None,
        title: str,
        message: str,
        type_: str,
    ) -> None:
        """
        Send to user if known, else fall back to default channel.
        Kept for backwards compatibility — prefer send_dm for personal notifications.
        Requires scopes: chat:write, im:write
        """
        channel = slack_user_id or self._cfg.default_channel_id
        blocks = _build_notification_blocks(title=title, message=message, type_=type_)
        await self._client.chat_postMessage(
            channel=channel,
            text=f"{_TYPE_EMOJI.get(type_, '🔔')} {title}",
            blocks=blocks,
        )
        logger.info("Slack notification sent to %s | title=%r", channel, title)

    async def send_celebration(
        self,
        *,
        channel_id: str | None,
        employee_name: str,
        celebration_type: str,
        years: int | None = None,
    ) -> None:
        """
        Broadcast celebration to the default channel — always public.
        Requires scope: chat:write
        """
        if celebration_type == "BIRTHDAY":
            title   = f"Happy Birthday, {employee_name}! 🎂"
            message = f"Today is *{employee_name}*'s birthday! 🎉 Wish them a wonderful day."
        else:
            ordinal = _ordinal(years)
            title   = f"Happy {ordinal} Work Anniversary, {employee_name}! 🏆"
            message = (
                f"*{employee_name}* is celebrating their *{ordinal} work anniversary* today! 🎊 "
                f"Thank you for {years} amazing year{'s' if years != 1 else ''} with us."
            )

        blocks  = _build_celebration_blocks(
            title=title,
            message=message,
            celebration_type=celebration_type,
        )
        # Always post to the default channel — never a DM
        channel = self._cfg.default_channel_id
        await self._client.chat_postMessage(channel=channel, text=title, blocks=blocks)
        logger.info(
            "Slack celebration posted to channel %s | %s for %s",
            channel, celebration_type, employee_name,
        )


# ── Block Kit helpers ──────────────────────────────────────────────────────────

_TYPE_EMOJI: dict[str, str] = {
    "REVIEW":      "📋",
    "REWARD":      "🏅",
    "SYSTEM":      "⚙️",
    "CELEBRATION": "🎉",
}


def _build_notification_blocks(*, title: str, message: str, type_: str) -> list[dict]:
    emoji = _TYPE_EMOJI.get(type_, "🔔")
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{emoji}  {title}*\n{message}"},
        },
        {"type": "divider"},
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"_{type_} notification · Aabhar_"}],
        },
    ]


def _build_celebration_blocks(
    *, title: str, message: str, celebration_type: str
) -> list[dict]:
    confetti = "🎂 🎉 🥳 🎈" if celebration_type == "BIRTHDAY" else "🏆 🎊 🥳 🎖️"
    return [
        {"type": "header", "text": {"type": "plain_text", "text": title, "emoji": True}},
        {"type": "section", "text": {"type": "mrkdwn", "text": message}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": confetti}]},
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": "Sent with ❤️ by Aabhar · Automated message"}
            ],
        },
    ]


def _ordinal(n: int | None) -> str:
    if n is None:
        return ""
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(
        n % 10 if n % 100 not in (11, 12, 13) else 0, "th"
    )
    return f"{n}{suffix}"