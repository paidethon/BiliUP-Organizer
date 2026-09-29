from __future__ import annotations

from sqlalchemy.orm import Session


def get_smtp_config(db: Session) -> dict:  # noqa: ANN001
    from app.services.settings_store import get_section_raw

    return get_section_raw(db, "smtp")


def send_email(db: Session, subject: str, html: str) -> None:
    """Frozen contract (implemented by the reminders agent):

    aiosmtplib over SMTP/SMTP_SSL per use_tls; From = from_addr,
    To = comma-separated to_addr; MIMEMultipart with HTML part, UTF-8.
    Raises ApiError(502, 'smtp_failed', detail) on failure.
    """
    raise NotImplementedError("implemented by the reminders agent")


def test_email(db: Session) -> tuple[bool, str]:
    """Send a test email; return (ok, message)."""
    raise NotImplementedError("implemented by the reminders agent")
