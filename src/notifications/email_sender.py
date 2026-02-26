# src/notifications/email_sender.py

"""
Lightweight async SMTP mailer.

Reads config from environment variables — never hard-code credentials.
Uses aiosmtplib so the event loop is never blocked.

Install dependency:  pip install aiosmtplib
"""

import logging
import os
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

logger = logging.getLogger(__name__)


# ── Config ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SMTPConfig:
    host: str
    port: int
    username: str
    password: str
    from_email: str
    use_tls: bool = True      # STARTTLS  (port 587)
    use_ssl: bool = False     # Implicit TLS (port 465)

    @classmethod
    def from_env(cls) -> "SMTPConfig":
        return cls(
            host=os.environ["SMTP_HOST"],
            port=int(os.environ.get("SMTP_PORT", "587")),
            username=os.environ["SMTP_USERNAME"],
            password=os.environ["SMTP_PASSWORD"],
            from_email=os.environ["SMTP_FROM_EMAIL"],
            use_tls=os.environ.get("SMTP_USE_TLS", "true").lower() == "true",
            use_ssl=os.environ.get("SMTP_USE_SSL", "false").lower() == "true",
        )


# ── Mailer ─────────────────────────────────────────────────────────────────────

class EmailSender:
    """
    Single-responsibility async email sender.

    One instance is created at startup and shared by the worker.
    The config is loaded once from the environment, failing fast if
    required variables are missing.
    """

    def __init__(self, config: SMTPConfig) -> None:
        self._cfg = config

    # -- Public API ------------------------------------------------------------

    async def send_notification_email(
        self,
        *,
        to_email: str,
        subject: str,
        body_html: str,
        body_text: str | None = None,
    ) -> None:
        """
        Send a single notification email.

        Raises on SMTP errors so the caller (worker) can decide whether to
        retry or log and skip.
        """
        message = self._build_message(
            to_email=to_email,
            subject=subject,
            body_html=body_html,
            body_text=body_text or self._html_to_plain(body_html),
        )
        await self._send(message)
        logger.info("Email sent to %s | subject=%r", to_email, subject)

    # -- Helpers ---------------------------------------------------------------

    def _build_message(
        self,
        *,
        to_email: str,
        subject: str,
        body_html: str,
        body_text: str,
    ) -> MIMEMultipart:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._cfg.from_email
        msg["To"] = to_email
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))
        return msg

    async def _send(self, message: MIMEMultipart) -> None:
        smtp_kwargs: dict = dict(
            hostname=self._cfg.host,
            port=self._cfg.port,
            username=self._cfg.username,
            password=self._cfg.password,
        )
        if self._cfg.use_ssl:
            smtp_kwargs["use_tls"] = True          # implicit TLS (port 465)
        else:
            smtp_kwargs["start_tls"] = self._cfg.use_tls  # STARTTLS (port 587)

        async with aiosmtplib.SMTP(**smtp_kwargs) as smtp:
            await smtp.send_message(message)

    @staticmethod
    def _html_to_plain(html: str) -> str:
        """Very basic HTML → plain text fallback."""
        import re
        return re.sub(r"<[^>]+>", "", html).strip()


# ── Template helpers ───────────────────────────────────────────────────────────

def build_notification_html(*, title: str, message: str, type_: str) -> str:
    """
    Minimal, inline-styled HTML email template.
    Replace with your branded template as needed.
    """
    type_color = {
        "REVIEW": "#4f46e5",
        "REWARD": "#f59e0b",
        "SYSTEM": "#6b7280",
        "CELEBRATION": "#ec4899",
    }.get(type_, "#6b7280")

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="UTF-8"><meta name="viewport" content="width=device-width"></head>
    <body style="margin:0;padding:0;background:#f3f4f6;font-family:Arial,sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:32px 0;">
        <tr>
          <td align="center">
            <table width="600" cellpadding="0" cellspacing="0"
                   style="background:#ffffff;border-radius:8px;overflow:hidden;
                          box-shadow:0 1px 3px rgba(0,0,0,.1);">
              <!-- Header -->
              <tr>
                <td style="background:{type_color};padding:24px 32px;">
                  <span style="color:#fff;font-size:12px;font-weight:600;
                               text-transform:uppercase;letter-spacing:.08em;">{type_}</span>
                </td>
              </tr>
              <!-- Body -->
              <tr>
                <td style="padding:32px;">
                  <h1 style="margin:0 0 16px;font-size:20px;color:#111827;">{title}</h1>
                  <p  style="margin:0;font-size:15px;line-height:1.6;color:#374151;">{message}</p>
                </td>
              </tr>
              <!-- Footer -->
              <tr>
                <td style="padding:16px 32px;background:#f9fafb;
                           border-top:1px solid #e5e7eb;
                           font-size:12px;color:#9ca3af;">
                  This is an automated message. Please do not reply.
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>
    """

def build_celebration_html(
    *,
    employee_name: str,
    celebration_type: str,   # "BIRTHDAY" | "WORK_ANNIVERSARY"
    years: int | None = None,
) -> tuple[str, str]:
    """
    Build a festive (subject, html) pair for birthday / work-anniversary emails.

    ``years`` is used for anniversaries (e.g. "5-year work anniversary").
    Returns a (subject, html_body) tuple so the caller has a ready-to-use subject.
    """
    if celebration_type == "BIRTHDAY":
        emoji = "🎂"
        subject = f"Happy Birthday, {employee_name}! 🎉"
        headline = f"Happy Birthday, {employee_name}!"
        body_copy = (
            "Wishing you a wonderful day filled with joy. "
            "The whole team is thinking of you — enjoy your special day!"
        )
        badge_label = "Birthday"
        badge_color = "#ec4899"   # pink
    else:
        ordinal = _ordinal(years) if years else ""
        emoji = "🏆"
        subject = f"Happy {ordinal} Work Anniversary, {employee_name}! 🎊"
        headline = f"Happy {ordinal} Work Anniversary, {employee_name}!"
        body_copy = (
            f"Today marks {years} incredible year{'s' if years != 1 else ''} "
            "with us. Thank you for everything you bring to the team — "
            "here's to many more milestones together!"
        )
        badge_label = "Work Anniversary"
        badge_color = "#7c3aed"   # purple

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head><meta charset="UTF-8"><meta name="viewport" content="width=device-width"></head>
    <body style="margin:0;padding:0;background:#f3f4f6;font-family:Arial,sans-serif;">
      <table width="100%" cellpadding="0" cellspacing="0" style="background:#f3f4f6;padding:32px 0;">
        <tr>
          <td align="center">
            <table width="600" cellpadding="0" cellspacing="0"
                   style="background:#ffffff;border-radius:8px;overflow:hidden;
                          box-shadow:0 1px 3px rgba(0,0,0,.1);">
              <!-- Festive header -->
              <tr>
                <td style="background:linear-gradient(135deg,{badge_color} 0%,#f9a8d4 100%);
                           padding:32px;text-align:center;">
                  <div style="font-size:48px;line-height:1;">{emoji}</div>
                  <span style="display:inline-block;margin-top:12px;padding:4px 14px;
                               background:rgba(255,255,255,.25);border-radius:99px;
                               color:#fff;font-size:11px;font-weight:700;
                               text-transform:uppercase;letter-spacing:.1em;">
                    {badge_label}
                  </span>
                </td>
              </tr>
              <!-- Body -->
              <tr>
                <td style="padding:36px 32px;text-align:center;">
                  <h1 style="margin:0 0 16px;font-size:22px;color:#111827;">{headline}</h1>
                  <p  style="margin:0;font-size:15px;line-height:1.7;color:#374151;
                              max-width:440px;margin:0 auto;">{body_copy}</p>
                </td>
              </tr>
              <!-- Confetti divider (pure CSS) -->
              <tr>
                <td style="padding:0 32px 24px;text-align:center;
                           font-size:20px;letter-spacing:4px;">
                  🎉 🎊 🥳 🎈 🎁
                </td>
              </tr>
              <!-- Footer -->
              <tr>
                <td style="padding:16px 32px;background:#f9fafb;
                           border-top:1px solid #e5e7eb;
                           font-size:12px;color:#9ca3af;text-align:center;">
                  Sent with ❤️ by your HR team · This is an automated message.
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </body>
    </html>
    """
    return subject, html


def _ordinal(n: int | None) -> str:
    """Return '1st', '2nd', '3rd', '4th', … for a given integer."""
    if n is None:
        return ""
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10 if n % 100 not in (11, 12, 13) else 0, "th")
    return f"{n}{suffix}"