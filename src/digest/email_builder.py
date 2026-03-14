"""
digest/email_builder.py
────────────────────────
Builds the weekly recognition digest email.

Design: matches the HDFC-style template used by notifications/email_sender.py.
  - Same _shell wrapper (navy header band, red stripe, footer)
  - Same _B palette (#E31837 red / #004C8F navy)
  - Arial only — no Segoe UI, no gradients, no pill badges
  - Points formula: sum(category_multipliers) × reviewer_weight
    (rating and seasonal_multiplier have been removed)
"""

from __future__ import annotations

from typing import Optional

from src.notifications.email_sender import _B, _shell, _sanitise

from .schemas import TopPerformer, WeeklyDigestData


def build_digest_html(data: WeeklyDigestData) -> tuple[str, str]:
    """
    Returns (subject, html_body) for the weekly digest email.
    """
    b = _B

    week_label = (
        f"{data.week_start.strftime('%d %b')} "
        f"– {data.week_end.strftime('%d %b %Y')}"
    )
    subject   = f"Weekly Recognition Digest — {week_label} | Aabhar"
    preheader = (
        f"{data.total_recognitions} "
        f"recognition{'s' if data.total_recognitions != 1 else ''} this week · "
        f"{data.unique_givers} giver{'s' if data.unique_givers != 1 else ''} · "
        f"{data.unique_receivers} "
        f"receiver{'s' if data.unique_receivers != 1 else ''}"
    )

    # ── Stat cards ─────────────────────────────────────────────────────────
    # Four equal-width cells in one row, each a navy-accented number + label.
    def _stat_cell(value: str, label: str, accent: str) -> str:
        return f"""
              <td align="center" style="padding:0 6px;">
                <table role="presentation" cellpadding="0" cellspacing="0"
                       style="width:116px;background:{b['card_bg']};
                              border:1px solid {b['border']};border-radius:2px;
                              border-top:3px solid {accent};">
                  <tr>
                    <td align="center" style="padding:16px 8px 14px;">
                      <span style="display:block;font-family:Arial,sans-serif;
                                   font-size:28px;font-weight:700;line-height:1;
                                   color:{accent};">
                        {value}
                      </span>
                      <span style="display:block;margin-top:6px;
                                   font-family:Arial,sans-serif;font-size:9.5px;
                                   font-weight:700;letter-spacing:1.2px;
                                   text-transform:uppercase;color:{b['txt_muted']};">
                        {label}
                      </span>
                    </td>
                  </tr>
                </table>
              </td>"""

    stats_row = f"""
        <!-- Stat cards -->
        <tr>
          <td style="padding:24px 26px 0;">
            <table role="presentation" width="100%"
                   cellpadding="0" cellspacing="0">
              <tr>
                {_stat_cell(str(data.total_recognitions),        "Recognitions", b["navy"])}
                {_stat_cell(str(data.unique_givers),             "Givers",       b["navy"])}
                {_stat_cell(str(data.unique_receivers),          "Receivers",    b["red"])}
                {_stat_cell(str(int(data.total_points_awarded)), "Points",       b["red"])}
              </tr>
            </table>
          </td>
        </tr>"""

    # ── Top performers table ────────────────────────────────────────────────
    def _performer_row(badge: str, badge_bg: str, person: Optional[TopPerformer]) -> str:
        if person is None:
            return ""
        unit = "recognition" if person.count == 1 else "recognitions"
        name = _sanitise(person.username)
        return f"""
              <tr>
                <td style="padding:11px 0;border-bottom:1px solid {b['divider']};">
                  <table role="presentation" width="100%"
                         cellpadding="0" cellspacing="0">
                    <tr>
                      <td valign="middle">
                        <!-- Badge -->
                        <table role="presentation" cellpadding="0"
                               cellspacing="0" style="display:inline-table;">
                          <tr>
                            <td style="background-color:{badge_bg};
                                       padding:3px 10px 4px;border-radius:2px;">
                              <span style="font-family:Arial,sans-serif;
                                           font-size:8.5px;font-weight:700;
                                           letter-spacing:1.2px;
                                           text-transform:uppercase;color:#FFFFFF;">
                                {badge}
                              </span>
                            </td>
                          </tr>
                        </table>
                        <!-- Name -->
                        <span style="margin-left:10px;font-family:Arial,sans-serif;
                                     font-size:13.5px;font-weight:600;
                                     color:{b['txt_head']};">
                          {name}
                        </span>
                      </td>
                      <td align="right" valign="middle">
                        <span style="font-family:Arial,sans-serif;font-size:12.5px;
                                     color:{b['txt_muted']};">
                          {person.count}&nbsp;{unit}
                        </span>
                      </td>
                    </tr>
                  </table>
                </td>
              </tr>"""

    performers_html = ""
    if data.top_giver or data.top_receiver:
        rows = (
            _performer_row("Top Giver",    b["navy"], data.top_giver)
            + _performer_row("Top Receiver", b["red"],  data.top_receiver)
        )
        performers_html = f"""
        <!-- Top performers -->
        <tr>
          <td style="padding:22px 26px 0;">
            <p style="margin:0 0 10px;font-family:Arial,sans-serif;font-size:9.5px;
                      font-weight:700;letter-spacing:1.3px;text-transform:uppercase;
                      color:{b['txt_muted']};">
              Top Performers This Week
            </p>
            <table role="presentation" width="100%"
                   cellpadding="0" cellspacing="0">
              {rows}
            </table>
          </td>
        </tr>"""

    # ── Empty-week notice ───────────────────────────────────────────────────
    empty_html = ""
    if data.total_recognitions == 0:
        empty_html = f"""
        <tr>
          <td style="padding:22px 26px 0;">
            <table role="presentation" width="100%" cellpadding="0"
                   cellspacing="0"
                   style="background-color:{b['navy_light']};
                          border-left:4px solid {b['navy']};border-radius:2px;">
              <tr>
                <td style="padding:14px 16px;">
                  <p style="margin:0;font-family:Arial,sans-serif;font-size:13px;
                            line-height:1.65;color:{b['txt_body']};">
                    No recognitions were submitted this week. We encourage managers
                    to promote the use of the Aabhar Recognition Platform and
                    foster a culture of peer acknowledgement within their teams.
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>"""

    # ── Points note ─────────────────────────────────────────────────────────
    points_note = ""
    if data.total_recognitions > 0:
        points_note = f"""
        <tr>
          <td style="padding:20px 26px 0;">
            <table role="presentation" width="100%" cellpadding="0"
                   cellspacing="0"
                   style="background-color:{b['navy_light']};
                          border-left:4px solid {b['navy']};border-radius:2px;">
              <tr>
                <td style="padding:12px 16px;">
                  <p style="margin:0;font-family:Arial,sans-serif;font-size:12px;
                            line-height:1.65;color:{b['txt_body']};">
                    <strong style="color:{b['navy']};">Points Methodology:&nbsp;</strong>
                    All recognition points are calculated as
                    <em>sum of selected category multipliers &times; reviewer weight</em>.
                    Multipliers are frozen as snapshots at the time of submission
                    to ensure historical totals remain reproducible.
                  </p>
                </td>
              </tr>
            </table>
          </td>
        </tr>"""

    # ── Sign-off ────────────────────────────────────────────────────────────
    signoff_html = f"""
        <tr>
          <td style="padding:26px 26px 32px;">
            <!-- Thin divider rule -->
            <table role="presentation" width="100%"
                   cellpadding="0" cellspacing="0"
                   style="margin-bottom:22px;">
              <tr>
                <td style="border-top:1px solid {b['divider']};
                           height:0;font-size:0;line-height:0;">&nbsp;</td>
              </tr>
            </table>

            <p style="margin:0 0 14px;font-family:Arial,sans-serif;font-size:13.5px;
                      line-height:1.8;color:{b['txt_body']};">
              Dear Manager,
            </p>
            <p style="margin:0 0 16px;font-family:Arial,sans-serif;font-size:13.5px;
                      line-height:1.8;color:{b['txt_body']};">
              Please find enclosed the weekly recognition summary for the period
              <strong>{week_label}</strong>. This digest is generated automatically
              every Monday and delivered to all managers on the Aabhar platform.
            </p>
            <p style="margin:0 0 22px;font-family:Arial,sans-serif;font-size:13.5px;
                      line-height:1.8;color:{b['txt_body']};">
              For a full breakdown of individual recognitions, category details,
              and employee point balances, please log in to the
              Aabhar Employee Recognition &amp; Rewards Platform.
            </p>

            <!-- Navy callout -->
            <table role="presentation" width="100%" cellpadding="0"
                   cellspacing="0"
                   style="margin:0 0 24px;background-color:{b['navy_light']};
                          border-left:4px solid {b['navy']};border-radius:2px;">
              <tr>
                <td style="padding:13px 16px;">
                  <p style="margin:0;font-family:Arial,sans-serif;font-size:13px;
                            line-height:1.65;color:{b['txt_body']};">
                    <strong style="color:{b['navy']};">Action Required:&nbsp;</strong>
                    Log in to Aabhar to review this week's recognitions in full,
                    manage team point allocations, and take any pending actions.
                  </p>
                </td>
              </tr>
            </table>

            <p style="margin:0;font-family:Arial,sans-serif;font-size:13.5px;
                      line-height:1.8;color:{b['txt_body']};">
              Yours sincerely,<br/>
              <strong style="color:{b['txt_head']};">
                Aabhar Recognition Platform
              </strong>
            </p>
          </td>
        </tr>"""

    # ── Content assembly ────────────────────────────────────────────────────
    content_html = f"""
        <!-- ═══ DIGEST HEADER ═══════════════════════════════════════════ -->
        <tr>
          <td style="padding:26px 26px 20px;
                     border-bottom:2px solid {b['divider']};">
            <!-- Badge -->
            <table role="presentation" cellpadding="0" cellspacing="0"
                   style="margin-bottom:12px;">
              <tr>
                <td style="background-color:{b['navy']};
                           padding:4px 13px 5px;border-radius:2px;">
                  <span style="font-family:Arial,sans-serif;font-size:9px;
                               font-weight:700;letter-spacing:1.4px;
                               text-transform:uppercase;color:#FFFFFF;">
                    Weekly Digest
                  </span>
                </td>
              </tr>
            </table>
            <!-- Title -->
            <h1 style="margin:0 0 5px;font-family:Arial,sans-serif;
                       font-size:19px;font-weight:700;line-height:1.3;
                       color:{b['txt_head']};">
              Weekly Recognition Summary
            </h1>
            <p style="margin:0;font-family:Arial,sans-serif;font-size:12px;
                      color:{b['txt_muted']};letter-spacing:0.2px;">
              {week_label}
            </p>
          </td>
        </tr>

        {stats_row}
        {performers_html}
        {empty_html}
        {points_note}
        {signoff_html}"""

    return subject, _shell(
        preheader=preheader,
        content_html=content_html,
    )