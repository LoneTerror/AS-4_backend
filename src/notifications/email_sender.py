"""
Lightweight async SMTP mailer — Abhaar brand edition.

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


# ── Brand palette (extracted from Abhaar logo) ────────────────────────────────
_BRAND = {
    "gradient_start": "#2D1B69",
    "gradient_mid":   "#7B2FBE",
    "gradient_end":   "#C0348A",
    "violet":         "#7B2FBE",
    "pink":           "#C0348A",
    "body_bg":        "#F7F8FC",
    "card_bg":        "#FFFFFF",
    "text_primary":   "#1F2937",
    "text_secondary": "#4B5563",
    "text_muted":     "#9CA3AF",
    "border":         "#E5E7EB",
    "footer_bg":      "#F3F4F6",
}

_TYPE_ACCENT = {
    "REVIEW":      "#4F46E5",
    "REWARD":      "#B45309",
    "SYSTEM":      "#374151",
    "CELEBRATION": "#C0348A",
}
_TYPE_LABEL = {
    "REVIEW":      "Performance Review",
    "REWARD":      "Reward & Recognition",
    "SYSTEM":      "System Notice",
    "CELEBRATION": "Celebration",
}


# ── Config ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SMTPConfig:
    host: str
    port: int
    username: str
    password: str
    from_email: str
    use_tls: bool = True
    use_ssl: bool = False

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
    def __init__(self, config: SMTPConfig) -> None:
        self._cfg = config

    async def send_notification_email(
        self,
        *,
        to_email: str,
        subject: str,
        body_html: str,
        body_text: str | None = None,
    ) -> None:
        # Never deliver to the SMTP sender's own address.
        if to_email.lower() == self._cfg.from_email.lower():
            logger.info(
                "Email suppressed — recipient %s matches SMTP sender, skipping.",
                to_email,
            )
            return

        message = self._build_message(
            to_email=to_email,
            subject=subject,
            body_html=body_html,
            body_text=body_text or self._html_to_plain(body_html),
        )
        await self._send(message)
        logger.info("Email sent to %s | subject=%r", to_email, subject)

    def _build_message(self, *, to_email, subject, body_html, body_text) -> MIMEMultipart:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"Abhaar <{self._cfg.from_email}>"
        msg["To"]      = to_email
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html",  "utf-8"))
        return msg

    async def _send(self, message: MIMEMultipart) -> None:
        smtp_kwargs: dict = dict(
            hostname=self._cfg.host,
            port=self._cfg.port,
            username=self._cfg.username,
            password=self._cfg.password,
        )
        if self._cfg.use_ssl:
            smtp_kwargs["use_tls"] = True
        else:
            smtp_kwargs["start_tls"] = self._cfg.use_tls
        async with aiosmtplib.SMTP(**smtp_kwargs) as smtp:
            await smtp.send_message(message)

    @staticmethod
    def _html_to_plain(html: str) -> str:
        import re
        return re.sub(r"<[^>]+>", "", html).strip()


# ── Shared layout shell ────────────────────────────────────────────────────────

def _email_shell(*, preheader: str, header_html: str, body_html: str) -> str:
    b = _BRAND
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <style>
    body,table,td,p,a{{margin:0;padding:0;border:0;}}
    body{{background:{b['body_bg']};font-family:'Segoe UI',Arial,sans-serif;}}
    @media only screen and (max-width:620px){{
      .card{{width:100%!important;border-radius:0!important;}}
      .pad{{padding:24px 20px!important;}}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background:{b['body_bg']};">
  <div style="display:none;max-height:0;overflow:hidden;font-size:1px;color:{b['body_bg']};">
    {preheader}&nbsp;&#847;&nbsp;&#847;&nbsp;&#847;
  </div>
  <table width="100%" cellpadding="0" cellspacing="0"
         style="background:{b['body_bg']};padding:40px 16px;">
    <tr><td align="center">
      <table class="card" width="600" cellpadding="0" cellspacing="0"
             style="background:{b['card_bg']};border-radius:12px;overflow:hidden;
                    box-shadow:0 4px 24px rgba(44,27,105,.10),0 1px 4px rgba(44,27,105,.06);">

        <!-- Logo bar -->
        <tr>
          <td align="center"
              style="background:linear-gradient(135deg,{b['gradient_start']} 0%,{b['gradient_mid']} 55%,{b['gradient_end']} 100%);
                     padding:22px 40px;">
            <span style="font-size:24px;font-weight:700;letter-spacing:.5px;
                         color:#fff;font-family:'Segoe UI',Arial,sans-serif;">
              Abh<span style="color:#F9A8D4;">aa</span>r
            </span>
          </td>
        </tr>

        {header_html}
        {body_html}

        <!-- Footer -->
        <tr>
          <td style="background:{b['footer_bg']};border-top:1px solid {b['border']};
                     padding:18px 40px;text-align:center;">
            <p style="margin:0 0 4px;font-size:12px;color:{b['text_muted']};
                      font-family:'Segoe UI',Arial,sans-serif;">
              This is an automated message from
              <strong style="color:{b['violet']};">Abhaar</strong>.
              Please do not reply.
            </p>
            <p style="margin:0;font-size:11px;color:{b['text_muted']};
                      font-family:'Segoe UI',Arial,sans-serif;">
              &copy; Abhaar &mdash; Employee Recognition Platform
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


# ── Notification email (REVIEW / REWARD / SYSTEM) ─────────────────────────────

def build_notification_html(*, title: str, message: str, type_: str) -> str:
    b      = _BRAND
    accent = _TYPE_ACCENT.get(type_, b["violet"])
    label  = _TYPE_LABEL.get(type_, type_.title())

    header_html = f"""
      <tr>
        <td style="padding:30px 40px 20px;border-bottom:1px solid {b['border']};">
          <span style="display:inline-block;padding:4px 14px;background:{accent};
                       border-radius:99px;font-size:11px;font-weight:700;
                       text-transform:uppercase;letter-spacing:.08em;color:#fff;
                       font-family:'Segoe UI',Arial,sans-serif;">
            {label}
          </span>
          <h1 style="margin:14px 0 0;font-size:21px;font-weight:700;line-height:1.35;
                     color:{b['text_primary']};font-family:'Segoe UI',Arial,sans-serif;">
            {title}
          </h1>
        </td>
      </tr>"""

    body_html = f"""
      <tr>
        <td class="pad" style="padding:26px 40px 36px;">
          <p style="margin:0;font-size:15px;line-height:1.75;
                    color:{b['text_secondary']};font-family:'Segoe UI',Arial,sans-serif;">
            {message}
          </p>
          <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:28px;">
            <tr>
              <td width="56" height="3" style="border-radius:2px;
                   background:linear-gradient(90deg,{b['gradient_start']},{b['gradient_end']});">
                &nbsp;
              </td>
              <td height="3" style="background:{b['border']};"></td>
            </tr>
          </table>
        </td>
      </tr>"""

    return _email_shell(
        preheader=f"{label}: {title}",
        header_html=header_html,
        body_html=body_html,
    )


# ── Celebration email (BIRTHDAY / WORK_ANNIVERSARY) ───────────────────────────

def build_celebration_html(
    *,
    employee_name: str,
    celebration_type: str,
    years: int | None = None,
    is_personal: bool = False,
) -> tuple[str, str]:
    b = _BRAND

    if celebration_type == "BIRTHDAY":
        badge_label  = "Birthday"
        badge_color  = b["pink"]
        if is_personal:
            subject    = f"Happy Birthday, {employee_name}"
            headline   = "Wishing You a Wonderful Birthday"
            salutation = f"Dear {employee_name},"
            body_copy  = (
                "On behalf of everyone at Abhaar, we want to take a moment to celebrate you today. "
                "Your presence, dedication, and the energy you bring to this team are truly valued. "
                "We hope this year brings you joy, meaningful growth, and everything you deserve. "
                "Happy Birthday."
            )
            cta_label  = None
        else:
            subject    = f"It's {employee_name}'s Birthday Today"
            headline   = f"{employee_name}'s Birthday"
            salutation = "A note for the team,"
            body_copy  = (
                f"Today is a special day for <strong>{employee_name}</strong>. "
                "Take a moment to reach out and acknowledge them — "
                "a kind word goes further than you think. "
                "Let's celebrate the people who make this team what it is."
            )
            cta_label  = f"Wish {employee_name.split()[0]} a Happy Birthday"

    else:  # WORK_ANNIVERSARY
        ordinal      = _ordinal(years)
        badge_label  = "Work Anniversary"
        badge_color  = b["violet"]
        yr_word      = f"{years} year{'s' if (years or 0) != 1 else ''}"

        if is_personal:
            subject    = f"Happy {ordinal} Work Anniversary, {employee_name}"
            headline   = f"Congratulations on {ordinal} Year{'s' if (years or 0) != 1 else ''}"
            salutation = f"Dear {employee_name},"
            body_copy  = (
                f"Today marks {yr_word} since you joined Abhaar — and what a journey it has been. "
                "Your commitment, consistency, and the standard you set for yourself "
                "do not go unnoticed. "
                "Thank you for the work you bring every day. Here's to the milestones still ahead."
            )
            cta_label  = None
        else:
            subject    = f"{employee_name} is Celebrating a Work Anniversary Today"
            headline   = f"{employee_name}'s {ordinal} Work Anniversary"
            salutation = "A note for the team,"
            body_copy  = (
                f"<strong>{employee_name}</strong> is marking their "
                f"<strong>{ordinal} anniversary</strong> with Abhaar today. "
                "Their contribution is a cornerstone of what we build together. "
                "Take a moment to acknowledge this milestone — "
                "recognition from peers is one of the most meaningful forms there is."
            )
            cta_label  = f"Congratulate {employee_name.split()[0]}"

    cta_html = ""
    if cta_label:
        cta_html = f"""
        <table cellpadding="0" cellspacing="0" style="margin-top:28px;">
          <tr>
            <td style="border-radius:6px;
                       background:linear-gradient(135deg,{b['gradient_start']},{b['gradient_mid']},{b['gradient_end']});">
              <span style="display:inline-block;padding:11px 26px;font-size:14px;
                           font-weight:600;color:#fff;
                           font-family:'Segoe UI',Arial,sans-serif;letter-spacing:.02em;">
                {cta_label}
              </span>
            </td>
          </tr>
        </table>"""

    header_html = f"""
      <tr>
        <td style="padding:28px 40px 20px;border-bottom:1px solid {b['border']};
                   background:linear-gradient(160deg,
                     rgba(44,27,105,.03) 0%,rgba(192,52,138,.04) 100%);">
          <span style="display:inline-block;padding:4px 14px;background:{badge_color};
                       border-radius:99px;font-size:11px;font-weight:700;
                       text-transform:uppercase;letter-spacing:.08em;color:#fff;
                       font-family:'Segoe UI',Arial,sans-serif;">
            {badge_label}
          </span>
          <h1 style="margin:14px 0 0;font-size:21px;font-weight:700;line-height:1.35;
                     color:{b['text_primary']};font-family:'Segoe UI',Arial,sans-serif;">
            {headline}
          </h1>
        </td>
      </tr>"""

    body_html = f"""
      <tr>
        <td class="pad" style="padding:26px 40px 36px;">
          <p style="margin:0 0 14px;font-size:12px;font-weight:700;
                    text-transform:uppercase;letter-spacing:.08em;
                    color:{badge_color};font-family:'Segoe UI',Arial,sans-serif;">
            {salutation}
          </p>
          <p style="margin:0;font-size:15px;line-height:1.75;
                    color:{b['text_secondary']};font-family:'Segoe UI',Arial,sans-serif;">
            {body_copy}
          </p>
          {cta_html}
          <table width="100%" cellpadding="0" cellspacing="0" style="margin-top:28px;">
            <tr>
              <td width="56" height="3" style="border-radius:2px;
                   background:linear-gradient(90deg,{b['gradient_start']},{b['gradient_end']});">
                &nbsp;
              </td>
              <td height="3" style="background:{b['border']};"></td>
            </tr>
          </table>
        </td>
      </tr>"""

    return subject, _email_shell(
        preheader=subject,
        header_html=header_html,
        body_html=body_html,
    )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ordinal(n: int | None) -> str:
    if n is None:
        return ""
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(
        n % 10 if n % 100 not in (11, 12, 13) else 0, "th"
    )
    return f"{n}{suffix}"