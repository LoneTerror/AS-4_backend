"""
digest/email_builder.py
────────────────────────
Builds the branded HTML digest email.
Reuses the _email_shell, _BRAND, and _ordinal helpers from
notifications/email_sender.py — copy the import path to match your project.
"""

from datetime import datetime
from typing import Optional

from src.notifications.email_sender import _email_shell, _BRAND

from .schemas import TopPerformer, WeeklyDigestData


def build_digest_html(data: WeeklyDigestData) -> tuple[str, str]:
    """
    Returns (subject, html_body) for the weekly digest email.
    """
    b = _BRAND

    week_label = (
        f"{data.week_start.strftime('%b %d')} – {data.week_end.strftime('%b %d, %Y')}"
    )
    subject = f"Weekly Recognition Digest · {week_label}"
    preheader = (
        f"{data.total_recognitions} recognition{'s' if data.total_recognitions != 1 else ''} "
        f"this week · {data.unique_givers} giver{'s' if data.unique_givers != 1 else ''} · "
        f"{data.unique_receivers} receiver{'s' if data.unique_receivers != 1 else ''}"
    )

    # ── Stat cards ──────────────────────────────────────────────────────────
    def stat_card(value: str, label: str, accent: str) -> str:
        return f"""
        <td align="center" style="padding:0 8px;">
          <table cellpadding="0" cellspacing="0"
                 style="background:{b['body_bg']};border-radius:10px;
                        border:1px solid {b['border']};width:130px;">
            <tr>
              <td align="center" style="padding:18px 12px 14px;">
                <p style="margin:0;font-size:30px;font-weight:700;line-height:1;
                           color:{accent};font-family:'Segoe UI',Arial,sans-serif;">
                  {value}
                </p>
                <p style="margin:6px 0 0;font-size:11px;font-weight:600;
                           text-transform:uppercase;letter-spacing:.07em;
                           color:{b['text_muted']};font-family:'Segoe UI',Arial,sans-serif;">
                  {label}
                </p>
              </td>
            </tr>
          </table>
        </td>"""

    stats_row = f"""
      <tr>
        <td style="padding:28px 40px 0;">
          <table cellpadding="0" cellspacing="0" width="100%">
            <tr>
              {stat_card(str(data.total_recognitions), "Recognitions",   b['violet'])}
              {stat_card(str(data.unique_givers),      "Givers",          b['gradient_mid'])}
              {stat_card(str(data.unique_receivers),   "Receivers",       b['pink'])}
              {stat_card(str(int(data.total_points_awarded)), "Points",   "#B45309")}
            </tr>
          </table>
        </td>
      </tr>"""

    # ── Top performer rows ───────────────────────────────────────────────────
    def performer_row(label: str, person: Optional[TopPerformer], accent: str) -> str:
        if person is None:
            return ""
        unit = "recognition" if person.count == 1 else "recognitions"
        return f"""
          <tr>
            <td style="padding:10px 0;border-bottom:1px solid {b['border']};">
              <table cellpadding="0" cellspacing="0" width="100%">
                <tr>
                  <td>
                    <span style="display:inline-block;padding:3px 10px;
                                 background:{accent};border-radius:99px;
                                 font-size:10px;font-weight:700;
                                 text-transform:uppercase;letter-spacing:.08em;
                                 color:#fff;font-family:'Segoe UI',Arial,sans-serif;">
                      {label}
                    </span>
                    <span style="margin-left:10px;font-size:15px;font-weight:600;
                                 color:{b['text_primary']};
                                 font-family:'Segoe UI',Arial,sans-serif;">
                      {person.username}
                    </span>
                  </td>
                  <td align="right">
                    <span style="font-size:13px;color:{b['text_secondary']};
                                 font-family:'Segoe UI',Arial,sans-serif;">
                      {person.count} {unit}
                    </span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>"""

    performers_block = ""
    has_performers = data.top_giver or data.top_receiver
    if has_performers:
        performers_block = f"""
      <tr>
        <td style="padding:24px 40px 0;">
          <p style="margin:0 0 12px;font-size:12px;font-weight:700;
                    text-transform:uppercase;letter-spacing:.08em;
                    color:{b['text_muted']};font-family:'Segoe UI',Arial,sans-serif;">
            Top Performers
          </p>
          <table cellpadding="0" cellspacing="0" width="100%">
            {performer_row("Top Giver",    data.top_giver,    b['violet'])}
            {performer_row("Top Receiver", data.top_receiver, b['pink'])}
          </table>
        </td>
      </tr>"""

    # ── Empty-week state ─────────────────────────────────────────────────────
    empty_block = ""
    if data.total_recognitions == 0:
        empty_block = f"""
      <tr>
        <td style="padding:24px 40px 0;text-align:center;">
          <p style="margin:0;font-size:14px;color:{b['text_muted']};
                    font-style:italic;font-family:'Segoe UI',Arial,sans-serif;">
            No recognitions were given this week. Encourage your team to start recognising!
          </p>
        </td>
      </tr>"""

    # ── Header ───────────────────────────────────────────────────────────────
    header_html = f"""
      <tr>
        <td style="padding:30px 40px 20px;border-bottom:1px solid {b['border']};">
          <span style="display:inline-block;padding:4px 14px;
                       background:linear-gradient(135deg,{b['gradient_start']},{b['gradient_end']});
                       border-radius:99px;font-size:11px;font-weight:700;
                       text-transform:uppercase;letter-spacing:.08em;color:#fff;
                       font-family:'Segoe UI',Arial,sans-serif;">
            Weekly Digest
          </span>
          <h1 style="margin:14px 0 4px;font-size:21px;font-weight:700;line-height:1.35;
                     color:{b['text_primary']};font-family:'Segoe UI',Arial,sans-serif;">
            Recognition Summary
          </h1>
          <p style="margin:0;font-size:13px;color:{b['text_muted']};
                    font-family:'Segoe UI',Arial,sans-serif;">
            {week_label}
          </p>
        </td>
      </tr>"""

    # ── Body ─────────────────────────────────────────────────────────────────
    body_html = f"""
      {stats_row}
      {performers_block}
      {empty_block}
      <tr>
        <td style="padding:28px 40px 36px;">
          <table width="100%" cellpadding="0" cellspacing="0">
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
        preheader=preheader,
        header_html=header_html,
        body_html=body_html,
    )
