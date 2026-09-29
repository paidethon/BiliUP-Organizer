"""SMTP email sending (synchronous, stdlib smtplib).

Deliberately uses blocking `smtplib` rather than aiosmtplib: emails are small,
rare and sent from APScheduler jobs and sync FastAPI endpoints, so a blocking
call of a few seconds is acceptable and keeps the code dependency-light.
"""

from __future__ import annotations

import html as html_mod
import re
import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlalchemy.orm import Session

from app.errors import ApiError

_SMTP_TIMEOUT = 15


def get_smtp_config(db: Session) -> dict:  # noqa: ANN001
    from app.services.settings_store import get_section_raw

    return get_section_raw(db, "smtp")


def _plain_text_alternative(html: str) -> str:
    """Rudimentary tag-stripped text part for multipart/alternative emails."""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(p|div|tr|h[1-6]|li|table)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def send_email(db: Session, subject: str, html: str) -> None:
    """Send an HTML email (with a plain-text alternative, both UTF-8).

    SMTP_SSL (usually port 465) when settings.use_tls is true, otherwise plain
    SMTP upgraded with STARTTLS. From = from_addr (falls back to username then
    the first recipient), To = the comma-separated to_addr list. Raises
    ApiError(502, 'smtp_failed', detail) on any failure, including a missing
    host/to_addr.
    """
    cfg = get_smtp_config(db)
    host = str(cfg.get("host") or "").strip()
    to_addr = str(cfg.get("to_addr") or "").strip()
    if not host or not to_addr:
        raise ApiError(502, "smtp_failed", "SMTP 未配置：缺少服务器地址或收件邮箱")
    try:
        port = int(cfg.get("port") or 465)
    except (TypeError, ValueError) as exc:
        raise ApiError(502, "smtp_failed", f"SMTP 端口无效：{cfg.get('port')}") from exc
    username = str(cfg.get("username") or "").strip()
    password = str(cfg.get("password") or "")
    from_addr = str(cfg.get("from_addr") or "").strip() or username or to_addr.split(",")[0].strip()
    recipients = [addr.strip() for addr in to_addr.split(",") if addr.strip()]

    message = MIMEMultipart("alternative")
    message["Subject"] = Header(subject, "utf-8")
    message["From"] = from_addr
    message["To"] = to_addr
    message.attach(MIMEText(_plain_text_alternative(html), "plain", "utf-8"))
    message.attach(MIMEText(html, "html", "utf-8"))

    try:
        if cfg.get("use_tls", True):
            with smtplib.SMTP_SSL(host, port, timeout=_SMTP_TIMEOUT) as client:
                if username and password:
                    client.login(username, password)
                client.sendmail(from_addr, recipients, message.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=_SMTP_TIMEOUT) as client:
                client.starttls()
                if username and password:
                    client.login(username, password)
                client.sendmail(from_addr, recipients, message.as_string())
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(502, "smtp_failed", f"SMTP 发送失败：{exc}") from exc


def test_email(db: Session) -> tuple[bool, str]:
    """Send a test email; return (ok, message) instead of raising."""
    try:
        send_email(
            db,
            "[BiliUP Organizer] SMTP 测试",
            "<p>这是一封来自 BiliUP Organizer 的测试邮件，收到即说明 SMTP 配置正确。</p>",
        )
    except ApiError as exc:
        return False, exc.message
    return True, "测试邮件已发送，请查收"
