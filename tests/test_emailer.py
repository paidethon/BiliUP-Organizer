from __future__ import annotations

import os
import smtplib
import tempfile
from email import message_from_string
from email.header import decode_header, make_header
from pathlib import Path

import pytest

os.environ.setdefault("DEMO_MODE", "1")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ENABLE_SCHEDULER", "0")
if "DATA_DIR" not in os.environ:
    os.environ["DATA_DIR"] = str(Path(tempfile.mkdtemp(prefix="biliup-emailer-")))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings, reset_settings_cache  # noqa: E402

reset_settings_cache()
get_settings()

from app.db import get_session_factory  # noqa: E402
from app.errors import ApiError  # noqa: E402
from app.main import app  # noqa: E402
from app.services import emailer  # noqa: E402
from app.services.emailer import send_email  # noqa: E402
from app.services.settings_store import update_section  # noqa: E402

SMTP_BASE = {
    "host": "smtp.test",
    "port": 465,
    "username": "user@test",
    "password": "secret",
    "from_addr": "from@test",
    "to_addr": "a@test,b@test",
    "use_tls": True,
}

HTML = "<html><body><p>你好 <b>世界</b></p><p>第二段</p></body></html>"


class FakeSMTP:
    """Records what emailer does; swap in for smtplib classes via monkeypatch."""

    instances: list[FakeSMTP]
    fail_send = False

    def __init__(self, host: str, port: int = 0, timeout: float | None = None) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.logged_in: tuple[str, str] | None = None
        self.started_tls = False
        self.sent: tuple[str, list[str], str] | None = None
        type(self).instances.append(self)

    def __enter__(self) -> FakeSMTP:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def login(self, user: str, password: str) -> None:
        self.logged_in = (user, password)

    def starttls(self) -> None:
        self.started_tls = True

    def sendmail(self, from_addr: str, to_addrs: list[str], msg: str) -> None:
        if self.fail_send:
            raise smtplib.SMTPException("relay refused")
        self.sent = (from_addr, list(to_addrs), msg)


@pytest.fixture(scope="module")
def db():
    with TestClient(app):
        pass
    session = get_session_factory()()
    yield session
    session.close()


@pytest.fixture
def smtp_env(db):  # noqa: ANN001, ANN201
    update_section(db, "smtp", {"host": "", "to_addr": ""})  # start from a clean slate
    FakeSMTP.instances = []
    FakeSMTP.fail_send = False
    yield
    update_section(db, "smtp", {"host": "", "to_addr": ""})


def _decoded_subject(raw_msg: str) -> str:
    parsed = message_from_string(raw_msg)
    return str(make_header(decode_header(parsed["Subject"])))


def _html_part(raw_msg: str) -> str:
    parsed = message_from_string(raw_msg)
    for part in parsed.walk():
        if part.get_content_type() == "text/html":
            return part.get_payload(decode=True).decode("utf-8")
    return ""


def _plain_part(raw_msg: str) -> str:
    parsed = message_from_string(raw_msg)
    for part in parsed.walk():
        if part.get_content_type() == "text/plain":
            return part.get_payload(decode=True).decode("utf-8")
    return ""


def test_send_email_ssl(db, smtp_env, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    update_section(db, "smtp", dict(SMTP_BASE))
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    plain_smtp = object()  # sentinel: must never be constructed
    monkeypatch.setattr(smtplib, "SMTP", lambda *a, **k: plain_smtp)

    send_email(db, "周报主题 <2026>", HTML)

    client = FakeSMTP.instances[-1]
    assert client.host == "smtp.test" and client.port == 465
    assert client.logged_in == ("user@test", "secret")
    assert client.started_tls is False
    from_addr, to_addrs, raw = client.sent
    assert from_addr == "from@test"
    assert to_addrs == ["a@test", "b@test"]
    parsed = message_from_string(raw)
    assert parsed["To"] == "a@test,b@test"
    assert parsed.get_content_type() == "multipart/alternative"
    assert _decoded_subject(raw) == "周报主题 <2026>"
    assert "你好" in _html_part(raw) and "<b>" in _html_part(raw)
    plain = _plain_part(raw)
    assert "你好" in plain and "<b>" not in plain  # tags stripped


def test_send_email_starttls(db, smtp_env, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    update_section(db, "smtp", {**SMTP_BASE, "use_tls": False, "port": 587})
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    send_email(db, "普通主题", HTML)

    client = FakeSMTP.instances[-1]
    assert client.host == "smtp.test" and client.port == 587
    assert client.started_tls is True
    assert client.logged_in == ("user@test", "secret")
    assert client.sent[1] == ["a@test", "b@test"]


def test_send_email_failure_raises(db, smtp_env, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    update_section(db, "smtp", dict(SMTP_BASE))
    FakeSMTP.fail_send = True
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)

    with pytest.raises(ApiError) as excinfo:
        send_email(db, "会失败", HTML)
    assert excinfo.value.status_code == 502
    assert excinfo.value.code == "smtp_failed"
    assert "失败" in excinfo.value.message


def test_send_email_unconfigured(db, smtp_env) -> None:  # noqa: ANN001
    with pytest.raises(ApiError) as excinfo:
        send_email(db, "没有配置", HTML)
    assert excinfo.value.code == "smtp_failed"
    assert "未配置" in excinfo.value.message


def test_test_email_ok(db, smtp_env, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    update_section(db, "smtp", dict(SMTP_BASE))
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)

    ok, message = emailer.test_email(db)
    assert ok is True and "已发送" in message
    raw = FakeSMTP.instances[-1].sent[2]
    assert _decoded_subject(raw) == "[BiliUP Organizer] SMTP 测试"


def test_test_email_failure(db, smtp_env, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: ANN001
    update_section(db, "smtp", dict(SMTP_BASE))
    FakeSMTP.fail_send = True
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)

    ok, message = emailer.test_email(db)
    assert ok is False and "失败" in message
