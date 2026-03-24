"""
Async SMTP mailer — Aabhar Employee Recognition & Rewards Platform.

Design language: Authentic HDFC Bank transactional email style.
  - White card background, no box-shadows
  - Navy (#004C8F) header band with logo
  - Thin red (#E31837) rule below header
  - Clean Arial body text, left-aligned
  - Security/info banner at the bottom (teal/info tone)
  - Minimal padding, no decorative elements
  - Footer: thin divider → small print → copyright line

Manager CC behaviour
────────────────────
  REVIEW and REWARD notification emails are CC'd to the employee's direct
  manager.  The manager's address is resolved lazily via
  ``internal_client.get_employee_manager_email`` and is injected as the
  ``cc_emails`` argument to ``send_notification_email``.  If no manager
  address is found the email is sent without a CC — it is never suppressed.

  Callers that already know the employee ID should pass it; the mailer then
  resolves the manager address internally so call-sites stay clean:

      await email_sender.send_notification_email(
          to_email   = employee.email,
          subject    = subject,
          body_html  = html,
          type_      = "REVIEW",
          employee_id = employee.employee_id,   # ← triggers manager CC
      )

  Alternatively, callers may pass ``cc_emails`` directly (e.g. in tests).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from src.common import internal_client

logger = logging.getLogger(__name__)


# ── Types that trigger a manager CC ──────────────────────────────────────────
_MANAGER_CC_TYPES: frozenset[str] = frozenset({"REVIEW", "REWARD"})


# ── Brand palette (HDFC-authentic) ────────────────────────────────────────────
_B = {
    "red":        "#E31837",
    "navy":       "#004C8F",
    "navy_dark":  "#003A6E",
    "white":      "#FFFFFF",
    "body_bg":    "#FFFFFF",   # HDFC emails have a plain white background
    "card_bg":    "#FFFFFF",
    "txt_head":   "#1A1A1A",
    "txt_body":   "#333333",
    "txt_muted":  "#666666",
    "border":     "#CCCCCC",
    "divider":    "#DDDDDD",
    "info_bg":    "#E8F4F8",   # teal-tinted info banner (matches HDFC secure banking banner)
    "info_border":"#1A8BAD",
    "info_txt":   "#0A4F63",
}

_TYPE_LABEL: dict[str, str] = {
    "REVIEW":       "Performance Review",
    "REWARD":       "Reward & Recognition",
    "SYSTEM":       "System Notice",
    "CELEBRATION":  "Recognition & Celebration",
    "ANNOUNCEMENT": "Company Announcement",
}

_LOGO_URL = (
    "https://raw.githubusercontent.com/"
    "rsah94614/AS-4_frontend/refs/heads/develop/public/logo.svg"
)


def _logo_html(height: int = 34) -> str:
    return (
        f'<img src="{_LOGO_URL}" height="{height}" alt="Aabhar"'
        f' style="display:block;border:0;height:{height}px;width:auto;" />'
    )


# ── SMTP config ───────────────────────────────────────────────────────────────

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


# ── Mailer ────────────────────────────────────────────────────────────────────

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
        # ── Manager CC ────────────────────────────────────────────────────────
        type_: str | None = None,
        employee_id: str | None = None,
        cc_emails: list[str] | None = None,
    ) -> None:
        """
        Send a notification email, optionally CC'ing the employee's manager.

        Manager CC is triggered automatically when:
          - ``type_`` is "REVIEW" or "REWARD", AND
          - ``employee_id`` is provided (used to look up the manager's address).

        ``cc_emails`` can be passed directly to override / supplement the
        automatic lookup (e.g. in unit tests or when the caller has already
        resolved the address).

        If the manager lookup returns None (no manager configured) the email
        is sent without CC — it is never suppressed.
        """
        if to_email.lower() == self._cfg.from_email.lower():
            logger.info("Email suppressed — recipient matches SMTP sender.")
            return

        # Resolve manager CC address when needed
        resolved_cc: list[str] = list(cc_emails or [])

        if (
            type_ in _MANAGER_CC_TYPES
            and employee_id
            and not resolved_cc          # skip lookup if caller supplied cc_emails
        ):
            try:
                manager_email = await internal_client.get_employee_manager_email(
                    employee_id
                )
                if manager_email:
                    resolved_cc.append(manager_email)
                    logger.debug(
                        "Manager CC resolved for employee %s: %s",
                        employee_id,
                        manager_email,
                    )
                else:
                    logger.debug(
                        "No manager found for employee %s — sending without CC.",
                        employee_id,
                    )
            except Exception:
                # Never let a failed CC lookup block the primary email.
                logger.warning(
                    "Manager email lookup failed for employee %s — sending without CC.",
                    employee_id,
                    exc_info=True,
                )

        msg = self._build_message(
            to_email=to_email,
            subject=subject,
            body_html=body_html,
            body_text=body_text or _html_to_plain(body_html),
            cc_emails=resolved_cc,
        )
        await self._send(msg)
        logger.info(
            "Email sent to %s%s | subject=%r",
            to_email,
            f" (CC: {', '.join(resolved_cc)})" if resolved_cc else "",
            subject,
        )

    def _build_message(
        self,
        *,
        to_email: str,
        subject: str,
        body_html: str,
        body_text: str,
        cc_emails: list[str] | None = None,
    ) -> MIMEMultipart:
        msg            = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"Aabhar Recognition Platform <{self._cfg.from_email}>"
        msg["To"]      = to_email
        if cc_emails:
            msg["Cc"]  = ", ".join(cc_emails)
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html",  "utf-8"))
        return msg

    async def _send(self, message: MIMEMultipart) -> None:
        # Collect all recipients (To + Cc) so aiosmtplib delivers to everyone
        recipients: list[str] = [message["To"]]
        if message["Cc"]:
            recipients.extend(
                addr.strip() for addr in message["Cc"].split(",") if addr.strip()
            )

        kw: dict = dict(
            hostname=self._cfg.host,
            port=self._cfg.port,
            username=self._cfg.username,
            password=self._cfg.password,
        )
        if self._cfg.use_ssl:
            kw["use_tls"] = True
        else:
            kw["start_tls"] = self._cfg.use_tls
        async with aiosmtplib.SMTP(**kw) as smtp:
            await smtp.send_message(message, recipients=recipients)


# ── Shared HTML shell ─────────────────────────────────────────────────────────

def _shell(*, preheader: str, content_html: str, show_security_banner: bool = True) -> str:
    """
    HDFC-authentic email wrapper.

    Layout (top → bottom):
    ┌──────────────────────────────────────┐
    │  Navy header band  [Logo]            │
    ├── 3px red rule ──────────────────────┤
    │                                      │
    │  content_html (body paragraphs)      │
    │                                      │
    ├── thin divider ──────────────────────┤
    │  [Secure Banking info banner]        │
    ├── thin divider ──────────────────────┤
    │  For more details... | © Aabhar      │
    └──────────────────────────────────────┘
    """
    b = _B

    security_banner = ""
    if show_security_banner:
        security_banner = f"""
        <!-- Security banner -->
        <tr>
          <td style="padding:0 0 16px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                   style="background-color:{b['info_bg']};border:1px solid {b['info_border']};">
              <tr>
                <td width="56" align="center" valign="middle"
                    style="padding:12px 0 12px 14px;">
                  <table role="presentation" cellpadding="0" cellspacing="0">
                    <tr>
                      <td align="center" valign="middle"
                          style="background-color:{b['info_border']};border-radius:50%;
                                 width:36px;height:36px;
                                 font-size:18px;line-height:36px;text-align:center;">
                        <span style="font-size:18px;line-height:36px;
                                     display:block;text-align:center;">&#128274;</span>
                      </td>
                    </tr>
                  </table>
                </td>
                <td style="padding:12px 14px 12px 10px;vertical-align:middle;">
                  <p style="margin:0;font-family:Arial,sans-serif;font-size:11.5px;
                            line-height:1.6;color:{b['info_txt']};">
                    <strong>SECURE PLATFORM</strong> &mdash;
                    This is an official communication from the Aabhar Employee
                    Recognition &amp; Rewards Platform. Do not share your login
                    credentials or personal details with anyone. Aabhar will never
                    ask for your password via email.
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <meta http-equiv="X-UA-Compatible" content="IE=edge"/>
  <title>Aabhar &mdash; Employee Recognition &amp; Rewards Platform</title>
  <style type="text/css">
    body,table,td,p,a,h1,h2,h3,span{{margin:0;padding:0;border:0;}}
    body{{background-color:#F4F4F4;
         font-family:Arial,Helvetica,sans-serif;
         -webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;}}
    table{{border-collapse:collapse;mso-table-lspace:0;mso-table-rspace:0;}}
    img{{border:0;height:auto;line-height:100%;outline:none;text-decoration:none;}}
    a{{color:{b['navy']};text-decoration:underline;}}
    @media only screen and (max-width:600px){{
      .outer-td{{padding:0 !important;}}
      .card{{width:100% !important;}}
      .body-pad{{padding:18px 16px !important;}}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background-color:#F4F4F4;">

<!-- Preheader ghost -->
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;
            font-size:1px;color:#F4F4F4;">
  {preheader}&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;
</div>

<!-- Outer wrapper -->
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background-color:#F4F4F4;">
  <tr>
    <td class="outer-td" align="center" style="padding:24px 16px;">

      <!-- Card -->
      <table class="card" role="presentation" width="600" cellpadding="0"
             cellspacing="0"
             style="background-color:{b['card_bg']};
                    border:1px solid {b['border']};">

        <!-- HEADER: navy band -->
        <tr>
          <td style="background-color:{b['navy']};padding:14px 20px;">
            {_logo_html(height=34)}
          </td>
        </tr>

        <!-- Red rule -->
        <tr>
          <td style="background-color:{b['red']};
                     height:3px;font-size:0;line-height:0;">&nbsp;</td>
        </tr>

        <!-- BODY -->
        <tr>
          <td class="body-pad" style="padding:24px 24px 8px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">

              {content_html}

              <!-- Divider -->
              <tr>
                <td style="padding:20px 0 16px;">
                  <table role="presentation" width="100%" cellpadding="0"
                         cellspacing="0">
                    <tr>
                      <td style="border-top:1px solid {b['divider']};
                                 height:0;font-size:0;">&nbsp;</td>
                    </tr>
                  </table>
                </td>
              </tr>

              {security_banner}

            </table>
          </td>
        </tr>

        <!-- FOOTER: small print + copyright -->
        <tr>
          <td style="padding:0 24px 16px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td style="border-top:1px solid {b['divider']};
                           padding-top:10px;">
                  <p style="margin:0 0 4px;font-family:Arial,sans-serif;
                            font-size:11px;color:{b['txt_muted']};">
                    For more details, please log in to the
                    <a href="#" style="color:{b['navy']};">Aabhar Platform</a>.
                  </p>
                  <p style="margin:0;font-family:Arial,sans-serif;
                            font-size:11px;color:{b['txt_muted']};">
                    &copy; Aabhar Employee Recognition &amp; Rewards Platform.
                    All rights reserved.
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>

      </table><!-- /card -->

    </td>
  </tr>
</table>

</body>
</html>"""


# ── Notification email (REVIEW / REWARD / SYSTEM / ANNOUNCEMENT) ─────────────

def build_notification_html(*, title: str, message: str, type_: str) -> str:
    title   = _sanitise(title)
    message = _sanitise(message)
    b       = _B
    label   = _TYPE_LABEL.get(type_, type_.replace("_", " ").title())

    if type_ == "REVIEW":
        display_title   = "Your Performance Review Is Ready"
        display_message = (
            "Your manager has shared a performance review on your profile. "
            "This is a moment to pause, reflect on the work you have put in, "
            "and hear how your contributions are being seen by those around you. "
            "We hope the feedback feels encouraging and gives you clarity on "
            "where you are headed."
        )
        action_text = (
            "Your review is available on the Aabhar platform whenever you are ready. "
            "Take your time going through it, and feel free to add your own "
            "response or acknowledgement once you have had a chance to reflect."
        )
    else:
        display_title   = title
        display_message = message
        action_text = (
            "Please log in to the Aabhar Employee Recognition &amp; Rewards Platform "
            "to view the complete details of this notification and take any required "
            "action. For queries, please contact your HR Administrator."
        )

    content_html = f"""
              <!-- Greeting -->
              <tr>
                <td style="padding-bottom:16px;">
                  <p style="margin:0;font-family:Arial,sans-serif;font-size:14px;
                            line-height:1.6;color:{b['txt_body']};">
                    Dear Team Member,
                  </p>
                </td>
              </tr>

              <!-- Notification type label -->
              <tr>
                <td style="padding-bottom:8px;">
                  <p style="margin:0;font-family:Arial,sans-serif;font-size:11px;
                            font-weight:700;letter-spacing:0.8px;
                            text-transform:uppercase;color:{b['navy']};">
                    {label}
                  </p>
                </td>
              </tr>

              <!-- Title -->
              <tr>
                <td style="padding-bottom:16px;
                           border-bottom:1px solid {b['divider']};">
                  <h2 style="margin:0;font-family:Arial,sans-serif;font-size:17px;
                             font-weight:700;color:{b['txt_head']};line-height:1.35;">
                    {display_title}
                  </h2>
                </td>
              </tr>

              <!-- Body paragraphs -->
              <tr>
                <td style="padding:16px 0 12px;">
                  <p style="margin:0 0 14px;font-family:Arial,sans-serif;
                            font-size:14px;line-height:1.7;color:{b['txt_body']};">
                    {display_message}
                  </p>
                  <p style="margin:0;font-family:Arial,sans-serif;
                            font-size:14px;line-height:1.7;color:{b['txt_body']};">
                    {action_text}
                  </p>
                </td>
              </tr>

              <!-- Sign-off -->
              <tr>
                <td style="padding-bottom:4px;">
                  <p style="margin:0;font-family:Arial,sans-serif;font-size:14px;
                            line-height:1.7;color:{b['txt_body']};">
                    Regards,<br/>
                    <strong>Aabhar Recognition Platform</strong>
                  </p>
                </td>
              </tr>"""

    return _shell(preheader=f"{label}: {display_title}", content_html=content_html)


# ── Celebration email (BIRTHDAY / WORK_ANNIVERSARY) ───────────────────────────

def build_celebration_html(
    *,
    employee_name: str,
    celebration_type: str,
    years: int | None = None,
    is_personal: bool = False,
) -> tuple[str, str]:
    employee_name = _sanitise(employee_name)
    b          = _B
    first_name = employee_name.split()[0]

    if celebration_type == "BIRTHDAY":
        label = "Birthday Recognition"

        if is_personal:
            subject    = f"Birthday Wishes — {employee_name} | Aabhar"
            headline   = "Warmest Birthday Greetings"
            salutation = f"Dear {employee_name},"
            paragraphs = [
                (
                    "On behalf of the leadership team and all your colleagues at Aabhar, "
                    "we extend our warmest wishes to you on this occasion of your birthday. "
                    "Today is a moment to recognise not only the personal milestone you are "
                    "celebrating, but also the meaningful contribution you make to this "
                    "organisation each and every day."
                ),
                (
                    "Your professionalism, dedication, and commitment to your work are "
                    "qualities that are deeply valued across the team. We hope the year "
                    "ahead brings you excellent health, continued professional growth, and "
                    "every success you aspire to achieve."
                ),
            ]
            milestone_line = ""

        else:
            subject    = f"Birthday Announcement — {employee_name} | Aabhar"
            headline   = f"Wishing {employee_name} a Happy Birthday"
            salutation = "Dear Team,"
            paragraphs = [
                (
                    f"We are pleased to inform you that today marks the birthday of our "
                    f"colleague, <strong>{employee_name}</strong>. We warmly invite all "
                    f"team members to take a moment to extend personal wishes and "
                    f"acknowledgement to {first_name} on this special occasion."
                ),
                (
                    f"We invite the entire team to join us in wishing {first_name} a very "
                    f"happy birthday and a wonderful year ahead filled with health, growth, "
                    f"and personal satisfaction."
                ),
            ]
            milestone_line = ""

    else:  # WORK_ANNIVERSARY
        ordinal     = _ordinal(years)
        yr_word     = f"{years} year{'s' if (years or 0) != 1 else ''}"
        label       = "Work Anniversary"

        if is_personal:
            subject    = f"Work Anniversary — {ordinal} Year with Aabhar | {employee_name}"
            headline   = f"Congratulations on Your {ordinal} Work Anniversary"
            salutation = f"Dear {employee_name},"
            paragraphs = [
                (
                    f"Today marks a distinguished milestone in your professional journey — "
                    f"your <strong>{ordinal} work anniversary</strong> with Aabhar. "
                    f"On behalf of the leadership team and the entire organisation, we extend "
                    f"our sincere congratulations and our profound gratitude for {yr_word} of "
                    f"dedicated and exemplary service."
                ),
                (
                    "Your dedication, the standards you hold yourself to, and the example "
                    "you set for colleagues around you are qualities that continue to "
                    "strengthen this organisation. We are privileged to have you as a "
                    "valued member of the Aabhar family and look forward to your continued "
                    "contributions."
                ),
            ]
            milestone_line = (
                f"You have completed <strong>{yr_word} of distinguished service</strong> "
                f"with Aabhar."
            )

        else:
            subject    = f"Work Anniversary — {employee_name} | {ordinal} Year with Aabhar"
            headline   = f"{employee_name}'s {ordinal} Work Anniversary"
            salutation = "Dear Team,"
            paragraphs = [
                (
                    f"We are delighted to announce that our esteemed colleague, "
                    f"<strong>{employee_name}</strong>, is today celebrating their "
                    f"<strong>{ordinal} work anniversary</strong> with Aabhar — representing "
                    f"{yr_word} of dedicated, professional service and sustained contribution "
                    f"to our shared goals."
                ),
                (
                    f"We encourage all members of the team to take a moment to formally "
                    f"acknowledge this achievement. Recognition from peers is among the most "
                    f"meaningful forms of appreciation an employee can receive, and "
                    f"{first_name}'s anniversary is a milestone that deserves to be "
                    f"celebrated with sincerity."
                ),
            ]
            milestone_line = (
                f"<strong>{employee_name}</strong> has completed "
                f"<strong>{yr_word} of service</strong> with Aabhar."
            )

    # Build paragraph HTML
    para_html = "".join(
        f'<p style="margin:0 0 14px;font-family:Arial,sans-serif;font-size:14px;'
        f'line-height:1.7;color:{b["txt_body"]};">{p}</p>'
        for p in paragraphs
    )

    # Optional milestone highlight line (plain inline text, no boxes)
    milestone_html = ""
    if milestone_line:
        milestone_html = f"""
              <tr>
                <td style="padding:4px 0 14px;">
                  <p style="margin:0;font-family:Arial,sans-serif;font-size:14px;
                            line-height:1.6;color:{b['navy']};">
                    {milestone_line}
                  </p>
                </td>
              </tr>"""

    content_html = f"""
              <!-- Greeting -->
              <tr>
                <td style="padding-bottom:16px;">
                  <p style="margin:0;font-family:Arial,sans-serif;font-size:14px;
                            line-height:1.6;color:{b['txt_body']};">
                    {salutation}
                  </p>
                </td>
              </tr>

              <!-- Label -->
              <tr>
                <td style="padding-bottom:8px;">
                  <p style="margin:0;font-family:Arial,sans-serif;font-size:11px;
                            font-weight:700;letter-spacing:0.8px;
                            text-transform:uppercase;color:{b['navy']};">
                    {label}
                  </p>
                </td>
              </tr>

              <!-- Headline -->
              <tr>
                <td style="padding-bottom:16px;
                           border-bottom:1px solid {b['divider']};">
                  <h2 style="margin:0;font-family:Arial,sans-serif;font-size:17px;
                             font-weight:700;color:{b['txt_head']};line-height:1.35;">
                    {headline}
                  </h2>
                </td>
              </tr>

              <!-- Milestone line -->
              {milestone_html}

              <!-- Body paragraphs -->
              <tr>
                <td style="padding:{'4' if milestone_line else '16'}px 0 12px;">
                  {para_html}
                </td>
              </tr>

              <!-- Sign-off -->
              <tr>
                <td style="padding-bottom:4px;">
                  <p style="margin:0;font-family:Arial,sans-serif;font-size:14px;
                            line-height:1.7;color:{b['txt_body']};">
                    Regards,<br/>
                    <strong>Aabhar Recognition Platform</strong>
                  </p>
                </td>
              </tr>"""

    return subject, _shell(preheader=subject, content_html=content_html)


# ── Utilities ─────────────────────────────────────────────────────────────────

def _html_to_plain(html: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", html).strip()


def _sanitise(text: str) -> str:
    import unicodedata
    result = []
    for ch in text:
        cp = ord(ch)
        if (0x2600 <= cp <= 0x27BF or 0x2900 <= cp <= 0x297F or
                0x2B00 <= cp <= 0x2BFF or 0xFE00 <= cp <= 0xFE0F or cp >= 0x1F300):
            continue
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Cf", "Cs") and ch not in ("\t", "\n"):
            continue
        result.append(ch)
    return "".join(result).strip()


def _ordinal(n: int | None) -> str:
    if n is None:
        return ""
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(
        n % 10 if n % 100 not in (11, 12, 13) else 0, "th"
    )
    return f"{n}{suffix}"