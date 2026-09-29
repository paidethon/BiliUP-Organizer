from __future__ import annotations

from sqlalchemy.orm import Session

TEMPLATE_DIR = "app/templates"


def build_report(db: Session) -> str:
    """Frozen contract (implemented by the reminders agent):

    Render app/templates/weekly_report.html.j2 (Jinja2) with:
      generated_at, totals (ups, groups, watched this week), stale list,
      never_watched list, important_unwatched list, new videos this week,
      open reminders count.
    Inline CSS only (email-safe), zh-CN copy. Returns the HTML string and
    stores it via api.weekly_routes.store_report (caller does that).
    """
    raise NotImplementedError("implemented by the reminders agent")


def send_weekly(db: Session) -> dict:
    """Build + email the weekly report; store it as latest.
    Returns {"ok": bool, "message": str}. Respects reminders.weekly_report_enabled."""
    raise NotImplementedError("implemented by the reminders agent")
