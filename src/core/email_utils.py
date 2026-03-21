"""
Email Utility Module
Handles sending password reset emails via Gmail SMTP
Design: Authentic HDFC Bank transactional email style
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ── Brand palette ──────────────────────────────────────────────────────────────
_NAVY    = "#004C8F"
_RED     = "#E31837"
_WHITE   = "#FFFFFF"
_BODY    = "#333333"
_MUTED   = "#666666"
_DIVIDER = "#DDDDDD"
_INFO_BG = "#E8F4F8"
_INFO_BD = "#1A8BAD"
_INFO_TX = "#0A4F63"
_BORDER  = "#CCCCCC"

_LOGO_URL = (
    "https://raw.githubusercontent.com/"
    "rsah94614/AS-4_frontend/refs/heads/develop/public/logo.svg"
)


def _shell(*, preheader: str, content_html: str) -> str:
    """HDFC-authentic email wrapper."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1.0"/>
  <title>Aabhar</title>
  <style>
    body,table,td,p,a{{margin:0;padding:0;border:0;}}
    body{{background-color:#F4F4F4;font-family:Arial,Helvetica,sans-serif;}}
    table{{border-collapse:collapse;}}
    img{{border:0;display:block;}}
    a{{color:{_NAVY};}}
    @media only screen and (max-width:600px){{
      .card{{width:100% !important;}}
      .bp{{padding:18px 16px !important;}}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background-color:#F4F4F4;">

<!-- Preheader ghost -->
<div style="display:none;max-height:0;overflow:hidden;font-size:1px;color:#F4F4F4;">
  {preheader}&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;&#8203;
</div>

<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background-color:#F4F4F4;">
  <tr>
    <td align="center" style="padding:24px 16px;">

      <table class="card" role="presentation" width="600" cellpadding="0"
             cellspacing="0"
             style="background-color:{_WHITE};border:1px solid {_BORDER};">

        <!-- Navy header -->
        <tr>
          <td style="background-color:{_NAVY};padding:14px 20px;">
            <img src="{_LOGO_URL}" height="34" alt="Aabhar"
                 style="height:34px;width:auto;border:0;display:block;"/>
          </td>
        </tr>

        <!-- Red rule -->
        <tr>
          <td style="background-color:{_RED};height:3px;font-size:0;">&nbsp;</td>
        </tr>

        <!-- Body -->
        <tr>
          <td class="bp" style="padding:24px 24px 8px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">

              {content_html}

              <!-- Divider -->
              <tr>
                <td style="padding:20px 0 16px;">
                  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                    <tr>
                      <td style="border-top:1px solid {_DIVIDER};height:0;font-size:0;">&nbsp;</td>
                    </tr>
                  </table>
                </td>
              </tr>

              <!-- Security banner -->
              <tr>
                <td style="padding-bottom:16px;">
                  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
                         style="background-color:{_INFO_BG};border:1px solid {_INFO_BD};">
                    <tr>
                      <td width="56" align="center" valign="middle"
                          style="padding:12px 0 12px 14px;">
                        <table role="presentation" cellpadding="0" cellspacing="0">
                          <tr>
                            <td align="center" valign="middle"
                                style="background-color:{_INFO_BD};border-radius:50%;
                                       width:36px;height:36px;
                                       font-size:18px;line-height:36px;
                                       text-align:center;">
                              <span style="font-size:18px;line-height:36px;
                                           display:block;text-align:center;">&#128274;</span>
                            </td>
                          </tr>
                        </table>
                      </td>
                      <td style="padding:12px 14px 12px 10px;vertical-align:middle;">
                        <p style="margin:0;font-family:Arial,sans-serif;font-size:11.5px;
                                  line-height:1.6;color:{_INFO_TX};">
                          <strong>SECURE PLATFORM</strong> &mdash;
                          Aabhar will never ask for your password via email or phone.
                          Do not share your reset link or credentials with anyone.
                          This link is valid for <strong>15 minutes</strong> only.
                        </p>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>

            </table>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="padding:0 24px 16px;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
              <tr>
                <td style="border-top:1px solid {_DIVIDER};padding-top:10px;">
                  <p style="margin:0 0 4px;font-family:Arial,sans-serif;
                            font-size:11px;color:{_MUTED};">
                    For more details, please log in to the
                    <a href="#" style="color:{_NAVY};">Aabhar Platform</a>.
                  </p>
                  <p style="margin:0;font-family:Arial,sans-serif;
                            font-size:11px;color:{_MUTED};">
                    &copy; Aabhar Employee Recognition &amp; Rewards Platform.
                    All rights reserved.
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>

      </table>
    </td>
  </tr>
</table>

</body>
</html>"""


def send_password_reset_email(email: str, reset_token: str, username: str) -> bool:
    """
    Send password reset email to user via Gmail SMTP.
    HDFC-authentic transactional email design.
    """
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
    reset_link   = f"{frontend_url}/reset-password?token={reset_token}"
    subject      = "Password Reset Request - Aabhar Employee Rewards System"

    content_html = f"""
              <!-- Greeting -->
              <tr>
                <td style="padding-bottom:16px;">
                  <p style="margin:0;font-family:Arial,sans-serif;font-size:14px;
                            line-height:1.6;color:{_BODY};">
                    Dear {username},
                  </p>
                </td>
              </tr>

              <!-- Label + title -->
              <tr>
                <td style="padding-bottom:8px;">
                  <p style="margin:0;font-family:Arial,sans-serif;font-size:11px;
                            font-weight:700;letter-spacing:0.8px;
                            text-transform:uppercase;color:{_NAVY};">
                    Account Security
                  </p>
                </td>
              </tr>
              <tr>
                <td style="padding-bottom:16px;border-bottom:1px solid {_DIVIDER};">
                  <h2 style="margin:0;font-family:Arial,sans-serif;font-size:17px;
                             font-weight:700;color:#1A1A1A;line-height:1.35;">
                    Password Reset Request
                  </h2>
                </td>
              </tr>

              <!-- Body -->
              <tr>
                <td style="padding:16px 0 12px;">
                  <p style="margin:0 0 14px;font-family:Arial,sans-serif;font-size:14px;
                            line-height:1.7;color:{_BODY};">
                    We received a request to reset your password for your Employee Rewards
                    System account. Click the link below to reset your password:
                  </p>

                  <!-- Reset link — plain underlined link, HDFC style (no fancy buttons) -->
                  <p style="margin:0 0 20px;font-family:Arial,sans-serif;font-size:14px;
                            line-height:1.7;">
                    <a href="{reset_link}"
                       style="color:{_NAVY};text-decoration:underline;word-break:break-all;">
                      {reset_link}
                    </a>
                  </p>

                  <p style="margin:0 0 14px;font-family:Arial,sans-serif;font-size:14px;
                            line-height:1.7;color:{_BODY};">
                    If you did not request a password reset, please ignore this email.
                    Your account will remain secure. If you believe someone else requested
                    this reset, please contact your system administrator immediately.
                  </p>

                  <p style="margin:0;font-family:Arial,sans-serif;font-size:14px;
                            line-height:1.7;color:{_BODY};">
                    This link will expire in <strong>15 minutes</strong>.
                  </p>
                </td>
              </tr>

              <!-- Sign-off -->
              <tr>
                <td style="padding-bottom:4px;">
                  <p style="margin:0;font-family:Arial,sans-serif;font-size:14px;
                            line-height:1.7;color:{_BODY};">
                    Regards,<br/>
                    <strong>Aabhar Recognition Platform</strong>
                  </p>
                </td>
              </tr>"""

    html_body = _shell(preheader="Password Reset Request — Aabhar", content_html=content_html)

    text_body = f"""
Password Reset Request — Aabhar

Dear {username},

We received a request to reset your password for your Employee Rewards System account.

Click this link to reset your password:
{reset_link}

This link will expire in 15 minutes.
If you did not request this reset, please ignore this email.

Regards,
Aabhar Recognition Platform
    """.strip()

    print("=" * 80)
    print("SENDING PASSWORD RESET EMAIL")
    print("=" * 80)
    print(f"To: {email}")
    print(f"Subject: {subject}")
    print("-" * 80)

    try:
        smtp_host       = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port       = int(os.getenv("SMTP_PORT", "587"))
        smtp_username   = os.getenv("SMTP_USERNAME")
        smtp_password   = os.getenv("SMTP_PASSWORD")
        smtp_from_email = os.getenv("SMTP_FROM_EMAIL", smtp_username)

        if not smtp_username or not smtp_password:
            print("ERROR: SMTP credentials not configured.")
            print("Reset token:", reset_token)
            return False

        msg            = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = smtp_from_email
        msg["To"]      = email
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(msg)

        print("Email sent successfully.")
        print("Reset token:", reset_token)
        return True

    except smtplib.SMTPAuthenticationError:
        print("SMTP Authentication Failed. Check your Gmail App Password.")
        print("Reset token:", reset_token)
        return False

    except Exception as e:
        print(f"Failed to send email: {e}")
        print("Reset token:", reset_token)
        return False


def send_password_reset_confirmation(email: str, username: str) -> bool:
    """Send confirmation email after successful password reset."""
    subject = "Password Successfully Reset - Aabhar Employee Rewards System"

    content_html = f"""
              <!-- Greeting -->
              <tr>
                <td style="padding-bottom:16px;">
                  <p style="margin:0;font-family:Arial,sans-serif;font-size:14px;
                            line-height:1.6;color:{_BODY};">
                    Dear {username},
                  </p>
                </td>
              </tr>

              <!-- Label + title -->
              <tr>
                <td style="padding-bottom:8px;">
                  <p style="margin:0;font-family:Arial,sans-serif;font-size:11px;
                            font-weight:700;letter-spacing:0.8px;
                            text-transform:uppercase;color:{_NAVY};">
                    Account Security
                  </p>
                </td>
              </tr>
              <tr>
                <td style="padding-bottom:16px;border-bottom:1px solid {_DIVIDER};">
                  <h2 style="margin:0;font-family:Arial,sans-serif;font-size:17px;
                             font-weight:700;color:#1A1A1A;line-height:1.35;">
                    Password Successfully Reset
                  </h2>
                </td>
              </tr>

              <!-- Body -->
              <tr>
                <td style="padding:16px 0 12px;">
                  <p style="margin:0 0 14px;font-family:Arial,sans-serif;font-size:14px;
                            line-height:1.7;color:{_BODY};">
                    Your password has been successfully reset. You can now log in to
                    your Employee Rewards System account using your new password.
                  </p>
                  <p style="margin:0;font-family:Arial,sans-serif;font-size:14px;
                            line-height:1.7;color:{_BODY};">
                    If you did not make this change, please contact your system
                    administrator immediately at 18002586161.
                  </p>
                </td>
              </tr>

              <!-- Sign-off -->
              <tr>
                <td style="padding-bottom:4px;">
                  <p style="margin:0;font-family:Arial,sans-serif;font-size:14px;
                            line-height:1.7;color:{_BODY};">
                    Regards,<br/>
                    <strong>Aabhar Recognition Platform</strong>
                  </p>
                </td>
              </tr>"""

    html_body = _shell(preheader="Password Reset Confirmation — Aabhar", content_html=content_html)

    text_body = f"""
Password Reset Confirmation — Aabhar

Dear {username},

Your password has been successfully reset.
You can now log in using your new password.

If you did not make this change, please contact your system administrator immediately.

Regards,
Aabhar Recognition Platform
    """.strip()

    print("=" * 80)
    print("SENDING PASSWORD RESET CONFIRMATION")
    print("=" * 80)
    print(f"To: {email}")

    try:
        smtp_host       = os.getenv("SMTP_HOST", "smtp.gmail.com")
        smtp_port       = int(os.getenv("SMTP_PORT", "587"))
        smtp_username   = os.getenv("SMTP_USERNAME")
        smtp_password   = os.getenv("SMTP_PASSWORD")
        smtp_from_email = os.getenv("SMTP_FROM_EMAIL", smtp_username)

        if not smtp_username or not smtp_password:
            print("SMTP not configured — skipping confirmation email.")
            return False

        msg            = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = smtp_from_email
        msg["To"]      = email
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(msg)

        print("Confirmation email sent successfully.")
        return True

    except Exception as e:
        print(f"Failed to send confirmation email: {e}")
        return False