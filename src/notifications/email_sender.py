"""
Async SMTP mailer — Aabhar Employee Recognition & Rewards Platform.

Design language: HDFC Bank transactional email style.
  - Colours : #E31837 (red) / #004C8F (navy)
  - Logo    : hosted at GitHub raw URL, referenced directly in <img src>.
              No file I/O — works identically on every OS and deployment.
  - Layout  : navy header band (red left stripe + logo) → 3 px red rule
              → classification badge → title → long-form body paragraphs
              → navy callout box → formal sign-off → disclaimer block
              → navy footer band (red left stripe).

Install: pip install aiosmtplib
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

logger = logging.getLogger(__name__)


# ── Brand palette ─────────────────────────────────────────────────────────────
_B = {
    "red":        "#E31837",
    "red_dark":   "#C0142F",
    "navy":       "#004C8F",
    "navy_dark":  "#003A6E",
    "navy_light": "#EEF4FB",    # tint for callout boxes
    "body_bg":    "#F0F2F5",
    "card_bg":    "#FFFFFF",
    "txt_head":   "#0D1B2A",
    "txt_body":   "#2C3E50",
    "txt_muted":  "#6B7280",
    "border":     "#D1D5DB",
    "divider":    "#E4E7EB",
    "footer_bg":  "#F7F8FA",
    "band_txt":   "#A8C4E0",    # subdued text on navy band
}

_BADGE_BG: dict[str, str] = {
    "REVIEW":       _B["navy"],
    "REWARD":       _B["red"],
    "SYSTEM":       _B["navy_dark"],
    "CELEBRATION":  _B["red"],
    "ANNOUNCEMENT": _B["navy"],
}

_TYPE_LABEL: dict[str, str] = {
    "REVIEW":       "Performance Review",
    "REWARD":       "Reward & Recognition",
    "SYSTEM":       "System Notice",
    "CELEBRATION":  "Recognition & Celebration",
    "ANNOUNCEMENT": "Company Announcement",
}


# ── Logo ──────────────────────────────────────────────────────────────────────
# Hosted on GitHub — no file I/O, no path issues, works on any OS.
# Update this constant if the repo or branch changes.

_LOGO_URL = (
    "https://raw.githubusercontent.com/"
    "rsah94614/AS-4_frontend/refs/heads/develop/public/logo.svg"
)


def _logo_html(height: int = 38) -> str:
    return (
        f'<img src="{_LOGO_URL}" height="{height}" alt="Aabhar"'
        f' style="display:block;border:0;height:{height}px;'
        f'max-height:{height}px;width:auto;" />'
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
    ) -> None:
        if to_email.lower() == self._cfg.from_email.lower():
            logger.info("Email suppressed — recipient matches SMTP sender.")
            return
        msg = self._build_message(
            to_email=to_email,
            subject=subject,
            body_html=body_html,
            body_text=body_text or _html_to_plain(body_html),
        )
        await self._send(msg)
        logger.info("Email sent to %s | subject=%r", to_email, subject)

    def _build_message(
        self, *, to_email: str, subject: str, body_html: str, body_text: str
    ) -> MIMEMultipart:
        msg            = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"Aabhar Recognition Platform <{self._cfg.from_email}>"
        msg["To"]      = to_email
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html",  "utf-8"))
        return msg

    async def _send(self, message: MIMEMultipart) -> None:
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
            await smtp.send_message(message)


# ── Shared HTML shell ─────────────────────────────────────────────────────────

def _shell(*, preheader: str, content_html: str) -> str:
    """
    Full HDFC-style email document wrapper.

    Anatomy
    -------
    [Navy band — red left stripe — logo — platform tagline]
    [3 px red rule]
    [content_html]                  ← injected by each builder function
    [thin divider]
    [Disclaimer block]
    [Navy band — red left stripe — copyright]
    [Below-card micro reference line]
    """
    b = _B

    return f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <meta http-equiv="X-UA-Compatible" content="IE=edge"/>
  <title>Aabhar &mdash; Employee Recognition &amp; Rewards Platform</title>
  <!--[if mso]>
  <noscript><xml><o:OfficeDocumentSettings>
  <o:PixelsPerInch>96</o:PixelsPerInch>
  </o:OfficeDocumentSettings></xml></noscript>
  <![endif]-->
  <style type="text/css">
    body,table,td,p,a,h1,h2,h3,span{{margin:0;padding:0;border:0;}}
    body{{background-color:{b['body_bg']};
         font-family:Arial,'Helvetica Neue',Helvetica,sans-serif;
         -webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;}}
    table{{border-collapse:collapse;mso-table-lspace:0;mso-table-rspace:0;}}
    img{{border:0;height:auto;line-height:100%;outline:none;
         text-decoration:none;-ms-interpolation-mode:bicubic;}}
    a{{color:{b['navy']};text-decoration:none;}}
    @media only screen and (max-width:640px){{
      .outer{{padding:0 !important;}}
      .card{{width:100% !important;border-radius:0 !important;}}
      .c-pad{{padding:22px 16px !important;}}
      .h-pad{{padding:20px 16px 16px !important;}}
      .f-pad{{padding:12px 16px !important;}}
      .hide-sm{{display:none !important;max-height:0 !important;
                overflow:hidden !important;mso-hide:all !important;}}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background-color:{b['body_bg']};">

<!-- ═══ PREHEADER ghost text ════════════════════════════════════════════════ -->
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;
            font-size:1px;color:{b['body_bg']};">
  {preheader}&nbsp;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;
  &#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;
  &#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;
</div>

<!-- ═══ OUTER TABLE ═════════════════════════════════════════════════════════ -->
<table class="outer" role="presentation" width="100%" cellpadding="0"
       cellspacing="0"
       style="background-color:{b['body_bg']};padding:36px 16px;">
  <tr>
    <td align="center" valign="top">

      <!-- ╔══════════════════════════════════════════════════════╗ -->
      <!-- ║  CARD                                               ║ -->
      <!-- ╚══════════════════════════════════════════════════════╝ -->
      <table class="card" role="presentation" width="620" cellpadding="0"
             cellspacing="0"
             style="background:{b['card_bg']};border-radius:3px;
                    border:1px solid {b['border']};
                    box-shadow:0 2px 10px rgba(0,0,0,0.10),
                               0 1px 3px rgba(0,0,0,0.06);">

        <!-- ── HEADER BAND ──────────────────────────────────────── -->
        <tr>
          <td style="background-color:{b['navy']};padding:0;
                     border-radius:3px 3px 0 0;">
            <table role="presentation" width="100%" cellpadding="0"
                   cellspacing="0">
              <tr>
                <!-- HDFC hallmark: red left-edge stripe -->
                <td width="6"
                    style="background-color:{b['red']};
                           font-size:0;line-height:0;">&nbsp;</td>

                <!-- Logo -->
                <td style="padding:16px 26px 14px;vertical-align:middle;">
                  {_logo_html(height=38)}
                </td>

                <!-- Platform tagline (hidden on mobile) -->
                <td class="hide-sm" align="right"
                    style="padding:16px 26px 14px 0;vertical-align:middle;">
                  <span style="font-family:Arial,sans-serif;font-size:8.5px;
                               font-weight:400;letter-spacing:1.5px;
                               color:{b['band_txt']};text-transform:uppercase;
                               white-space:nowrap;">
                    Employee Recognition &amp; Rewards Platform
                  </span>
                </td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- ── RED RULE (HDFC signature element) ───────────────── -->
        <tr>
          <td style="background-color:{b['red']};height:3px;
                     font-size:0;line-height:0;">&nbsp;</td>
        </tr>

        <!-- ── CONTENT (injected) ───────────────────────────────── -->
        {content_html}

        <!-- ── DIVIDER before disclaimer ────────────────────────── -->
        <tr>
          <td style="padding:0 26px;">
            <table role="presentation" width="100%" cellpadding="0"
                   cellspacing="0">
              <tr>
                <td style="border-top:1px solid {b['divider']};
                           height:0;font-size:0;line-height:0;">&nbsp;</td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- ── DISCLAIMER ────────────────────────────────────────── -->
        <tr>
          <td style="background-color:{b['footer_bg']};
                     padding:18px 26px 22px;">
            <p style="margin:0 0 8px;font-family:Arial,sans-serif;
                      font-size:10px;line-height:1.65;color:{b['txt_muted']};">
              <strong style="color:#4B5563;">IMPORTANT NOTICE:</strong>
              This is a system-generated communication from the Aabhar Employee
              Recognition &amp; Rewards Platform. Please do not reply to this
              message. This communication is intended solely for the named
              recipient. If you have received this in error, please notify your
              HR Administrator immediately and permanently delete this message
              and any attachments.
            </p>
            <p style="margin:0;font-family:Arial,sans-serif;font-size:9.5px;
                      line-height:1.6;color:{b['txt_muted']};">
              The contents of this communication are confidential and may be
              subject to privilege. Unauthorised reading, copying, disclosure,
              or distribution is strictly prohibited. Aabhar and its affiliated
              entities accept no liability for the completeness or accuracy of
              this message if transmitted over public networks.
            </p>
          </td>
        </tr>

        <!-- ── FOOTER BAND ───────────────────────────────────────── -->
        <tr>
          <td style="background-color:{b['navy']};padding:0;
                     border-radius:0 0 3px 3px;">
            <table role="presentation" width="100%" cellpadding="0"
                   cellspacing="0">
              <tr>
                <td width="6"
                    style="background-color:{b['red']};
                           font-size:0;line-height:0;">&nbsp;</td>
                <td class="f-pad" style="padding:13px 26px;">
                  <table role="presentation" width="100%" cellpadding="0"
                         cellspacing="0">
                    <tr>
                      <td valign="middle">
                        <p style="margin:0 0 2px;font-family:Arial,sans-serif;
                                  font-size:10px;color:{b['band_txt']};
                                  letter-spacing:0.2px;">
                          Aabhar &mdash; Employee Recognition &amp; Rewards Platform
                        </p>
                        <p style="margin:0;font-family:Arial,sans-serif;
                                  font-size:9px;color:#5A7FA0;">
                          &copy; Aabhar. All rights reserved.
                          &nbsp;|&nbsp; Automated Notification
                        </p>
                      </td>
                      <td class="hide-sm" align="right" valign="middle">
                        <span style="font-family:Arial,sans-serif;
                                     font-size:14px;font-weight:700;
                                     color:#FFFFFF;letter-spacing:0.3px;">
                          Aabhar
                        </span>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>
            </table>
          </td>
        </tr>

      </table><!-- /CARD -->

      <!-- Below-card micro line -->
      <table role="presentation" width="620" cellpadding="0" cellspacing="0">
        <tr>
          <td style="padding:9px 0 0;text-align:center;">
            <p style="margin:0;font-family:Arial,sans-serif;font-size:9px;
                      color:#9CA3AF;letter-spacing:0.4px;">
              Aabhar Employee Recognition &amp; Rewards Platform
              &nbsp;|&nbsp; Automated Notification System
            </p>
          </td>
        </tr>
      </table>

    </td>
  </tr>
</table><!-- /OUTER -->

</body>
</html>"""


# ── Notification email (REVIEW / REWARD / SYSTEM / ANNOUNCEMENT) ─────────────

def build_notification_html(*, title: str, message: str, type_: str) -> str:
    title   = _sanitise(title)
    message = _sanitise(message)
    b         = _B
    badge_bg  = _BADGE_BG.get(type_, b["navy"])
    label     = _TYPE_LABEL.get(type_, type_.replace("_", " ").title())

    # REVIEW: privacy-safe teaser — full content is in-app only
    if type_ == "REVIEW":
        display_title   = "A Performance Review Has Been Submitted"
        display_message = (
            "A new performance review has been submitted and recorded against your "
            "employee profile on the Aabhar platform. In the interest of "
            "confidentiality, the complete content of this review is not included "
            "in this communication."
        )
        action_text = (
            "Please log in to the Aabhar Employee Recognition &amp; Rewards Platform "
            "at your earliest convenience to access the full review and take any "
            "action that may be required."
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
        <!-- Classification badge + title -->
        <tr>
          <td class="h-pad"
              style="padding:26px 26px 20px;
                     border-bottom:2px solid {b['divider']};">
            <!-- Badge -->
            <table role="presentation" cellpadding="0" cellspacing="0"
                   style="margin-bottom:12px;">
              <tr>
                <td style="background-color:{badge_bg};padding:4px 13px 5px;
                           border-radius:2px;">
                  <span style="font-family:Arial,sans-serif;font-size:9px;
                               font-weight:700;letter-spacing:1.4px;
                               text-transform:uppercase;color:#FFFFFF;">
                    {label}
                  </span>
                </td>
              </tr>
            </table>
            <!-- Title -->
            <h1 style="margin:0;font-family:Arial,sans-serif;font-size:19px;
                       font-weight:700;line-height:1.3;color:{b['txt_head']};">
              {display_title}
            </h1>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td class="c-pad" style="padding:26px 26px 8px;">

            <p style="margin:0 0 14px;font-family:Arial,sans-serif;font-size:13.5px;
                      line-height:1.75;color:{b['txt_body']};">
              Dear Team Member,
            </p>

            <p style="margin:0 0 22px;font-family:Arial,sans-serif;font-size:13.5px;
                      line-height:1.8;color:{b['txt_body']};">
              {display_message}
            </p>

            <!-- Navy callout box -->
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                   style="margin:0 0 24px;background-color:{b['navy_light']};
                          border-left:4px solid {b['navy']};border-radius:2px;">
              <tr>
                <td style="padding:14px 16px;">
                  <p style="margin:0;font-family:Arial,sans-serif;font-size:13px;
                            line-height:1.65;color:{b['txt_body']};">
                    <strong style="color:{b['navy']};">Next Step:&nbsp;</strong>
                    {action_text}
                  </p>
                </td>
              </tr>
            </table>

            <!-- Sign-off -->
            <p style="margin:0 0 28px;font-family:Arial,sans-serif;
                      font-size:13.5px;line-height:1.8;color:{b['txt_body']};">
              Yours sincerely,<br/>
              <strong style="color:{b['txt_head']};">
                Aabhar Recognition Platform
              </strong>
            </p>

          </td>
        </tr>"""

    return _shell(
        preheader=f"{label}: {display_title}",
        content_html=content_html,
    )


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

    # ── Copy matrix ───────────────────────────────────────────────────────────
    if celebration_type == "BIRTHDAY":
        badge_bg    = b["red"]
        badge_label = "Birthday Recognition"

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
                    "qualities that are deeply valued across the team. The effort you bring "
                    "consistently reflects the culture we strive to build at Aabhar, and "
                    "it does not go unnoticed."
                ),
                (
                    "We hope that the year ahead brings you excellent health, continued "
                    "professional growth, personal fulfilment, and every success you aspire "
                    "to achieve. May this be a truly memorable birthday for you and your "
                    "loved ones."
                ),
            ]
            milestone_html = ""
            cta_label      = None

        else:
            subject    = f"Birthday Announcement — {employee_name} | Aabhar"
            headline   = f"Recognising {employee_name} on Their Birthday"
            salutation = "Dear Team,"
            paragraphs = [
                (
                    f"We are pleased to bring to your attention that today marks the birthday "
                    f"of our colleague, <strong>{employee_name}</strong>. We warmly invite "
                    f"all team members to take a moment to extend personal wishes and "
                    f"acknowledgement to {first_name} on this special occasion."
                ),
                (
                    "The recognition of our colleagues as individuals — distinct from and in "
                    "addition to their professional roles — is a fundamental part of the "
                    "culture we are building at Aabhar. A brief, genuine message of goodwill "
                    "is one of the most impactful gestures we can offer one another."
                ),
                (
                    f"We invite the entire team to join us in wishing {first_name} a very "
                    f"happy birthday and a wonderful year ahead filled with health, growth, "
                    f"and personal satisfaction."
                ),
            ]
            milestone_html = ""
            cta_label      = f"Send Your Wishes to {first_name}"

    else:  # WORK_ANNIVERSARY
        ordinal     = _ordinal(years)
        yr_word     = f"{years} year{'s' if (years or 0) != 1 else ''}"
        badge_bg    = b["navy"]
        badge_label = "Work Anniversary"

        milestone_html = f"""
            <table role="presentation" width="100%" cellpadding="0"
                   cellspacing="0" style="margin:20px 0;">
              <tr>
                <td align="center"
                    style="background-color:{b['navy']};border-radius:2px;
                           padding:20px 16px;">
                  <span style="font-family:Arial,sans-serif;font-size:42px;
                               font-weight:700;color:#FFFFFF;line-height:1;
                               display:block;">{years}</span>
                  <span style="font-family:Arial,sans-serif;font-size:9px;
                               font-weight:700;letter-spacing:2px;
                               text-transform:uppercase;color:{b['band_txt']};
                               display:block;margin-top:5px;">
                    Year{'s' if (years or 0) != 1 else ''}&nbsp;of&nbsp;Distinguished&nbsp;Service
                  </span>
                </td>
              </tr>
            </table>"""

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
                    "Milestones of this nature are not simply a measure of time served — "
                    "they are a reflection of consistent commitment, professional integrity, "
                    "and the genuine investment you have made in the people and the mission "
                    "of this organisation. The contributions you have delivered across this "
                    "period are woven into the very foundations of what Aabhar has become."
                ),
                (
                    "Your dedication, the standards you hold yourself to, and the example "
                    "you set for colleagues around you are qualities that continue to "
                    "strengthen this organisation. We are privileged to have you as a "
                    "valued member of the Aabhar family."
                ),
                (
                    "We look forward with great anticipation to your continued contributions "
                    "and the milestones that lie ahead. Thank you sincerely for everything "
                    "you have brought to this team."
                ),
            ]
            cta_label = None

        else:
            subject    = f"Work Anniversary — {employee_name} | {ordinal} Year with Aabhar"
            headline   = f"{employee_name}'s {ordinal} Work Anniversary"
            salutation = "Dear Team,"
            paragraphs = [
                (
                    f"We are delighted to announce that our esteemed colleague, "
                    f"<strong>{employee_name}</strong>, is today celebrating their "
                    f"<strong>{ordinal} work anniversary</strong> with Aabhar. This milestone "
                    f"represents {yr_word} of dedicated, professional service and sustained "
                    f"contribution to our shared goals."
                ),
                (
                    f"{employee_name}'s tenure with the organisation reflects the kind of "
                    f"consistency, commitment, and professional depth that elevates every "
                    f"team. The institutional knowledge and the steady example that "
                    f"{first_name} brings to the workplace benefit colleagues at every level."
                ),
                (
                    f"We encourage all members of the team to take a moment to formally "
                    f"acknowledge this achievement. Recognition from peers is among the "
                    f"most meaningful forms of appreciation an employee can receive, and "
                    f"{first_name}'s anniversary is a milestone that deserves to be "
                    f"celebrated with sincerity."
                ),
            ]
            cta_label = f"Recognise {first_name}'s Contribution"

    # ── CTA button ────────────────────────────────────────────────────────────
    cta_html = ""
    if cta_label:
        cta_html = f"""
            <table role="presentation" cellpadding="0" cellspacing="0"
                   style="margin-top:20px;">
              <tr>
                <td style="background-color:{b['navy']};border-radius:2px;
                           border-bottom:3px solid {b['navy_dark']};">
                  <span style="display:inline-block;padding:12px 28px;
                               font-family:Arial,sans-serif;font-size:12.5px;
                               font-weight:700;color:#FFFFFF;letter-spacing:0.5px;">
                    {cta_label}
                  </span>
                </td>
              </tr>
            </table>
            <p style="margin:9px 0 0;font-family:Arial,sans-serif;font-size:10px;
                      color:{b['txt_muted']};">
              Log in to Aabhar to send a personalised recognition message.
            </p>"""

    # ── Paragraph block ───────────────────────────────────────────────────────
    para_html = "".join(
        f'<p style="margin:0 0 16px;font-family:Arial,sans-serif;font-size:13.5px;'
        f'line-height:1.8;color:{b["txt_body"]};">{p}</p>'
        for p in paragraphs
    )

    content_html = f"""
        <!-- Badge + headline -->
        <tr>
          <td class="h-pad"
              style="padding:26px 26px 20px;
                     border-bottom:2px solid {b['divider']};">
            <table role="presentation" cellpadding="0" cellspacing="0"
                   style="margin-bottom:12px;">
              <tr>
                <td style="background-color:{badge_bg};padding:4px 13px 5px;
                           border-radius:2px;">
                  <span style="font-family:Arial,sans-serif;font-size:9px;
                               font-weight:700;letter-spacing:1.4px;
                               text-transform:uppercase;color:#FFFFFF;">
                    {badge_label}
                  </span>
                </td>
              </tr>
            </table>
            <h1 style="margin:0;font-family:Arial,sans-serif;font-size:19px;
                       font-weight:700;line-height:1.3;color:{b['txt_head']};">
              {headline}
            </h1>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td class="c-pad" style="padding:26px 26px 8px;">

            <p style="margin:0 0 18px;font-family:Arial,sans-serif;
                      font-size:12.5px;font-weight:700;letter-spacing:0.3px;
                      color:{badge_bg};">
              {salutation}
            </p>

            {para_html}

            {milestone_html}

            <!-- Navy callout -->
            <table role="presentation" width="100%" cellpadding="0"
                   cellspacing="0"
                   style="margin:8px 0 20px;background-color:{b['navy_light']};
                          border-left:4px solid {b['navy']};border-radius:2px;">
              <tr>
                <td style="padding:14px 16px;">
                  <p style="margin:0;font-family:Arial,sans-serif;font-size:13px;
                            line-height:1.65;color:{b['txt_body']};">
                    <strong style="color:{b['navy']};">Platform Notice:&nbsp;</strong>
                    Log in to the Aabhar Employee Recognition &amp; Rewards Platform
                    to view this occasion and send a personalised message of
                    recognition directly to the recipient.
                  </p>
                </td>
              </tr>
            </table>

            {cta_html}

            <!-- Sign-off -->
            <p style="margin:24px 0 28px;font-family:Arial,sans-serif;
                      font-size:13.5px;line-height:1.8;color:{b['txt_body']};">
              Yours sincerely,<br/>
              <strong style="color:{b['txt_head']};">
                Aabhar Recognition Platform
              </strong>
            </p>

          </td>
        </tr>"""

    return subject, _shell(
        preheader=subject,
        content_html=content_html,
    )


# ── Utilities ─────────────────────────────────────────────────────────────────

def _html_to_plain(html: str) -> str:
    import re
    return re.sub(r"<[^>]+>", "", html).strip()


def _sanitise(text: str) -> str:
    """
    Strip emoji and non-printable Unicode characters from a display string.

    Keeps: printable ASCII, accented Latin characters, common punctuation.
    Removes: emoji, dingbats, pictographs, and other non-printing codepoints
    that render as boxes or question marks in Outlook and corporate webmail.

    Unicode ranges dropped:
      U+2600–U+27BF  Miscellaneous Symbols, Dingbats
      U+2900–U+297F  Supplemental Arrows
      U+2B00–U+2BFF  Miscellaneous Symbols and Arrows
      U+1F300+       Emoji, pictographs, symbols (main emoji block)
    """
    import unicodedata
    result = []
    for ch in text:
        cp = ord(ch)
        if (0x2600 <= cp <= 0x27BF or
                0x2900 <= cp <= 0x297F or
                0x2B00 <= cp <= 0x2BFF or
                0xFE00 <= cp <= 0xFE0F or   # variation selectors (emoji modifiers)
                cp >= 0x1F300):
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