from __future__ import annotations

import os
import tempfile
from pathlib import Path

import httpx
import pytest
import respx

os.environ.setdefault("DEMO_MODE", "1")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ENABLE_SCHEDULER", "0")
if "DATA_DIR" not in os.environ:
    os.environ["DATA_DIR"] = str(Path(tempfile.mkdtemp(prefix="biliup-ai-")))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings, reset_settings_cache  # noqa: E402

reset_settings_cache()
get_settings()

from app.db import get_session_factory  # noqa: E402
from app.errors import ApiError  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AiSuggestion, GroupLocal, UpUser  # noqa: E402
from app.services.ai_classifier import decide, run_classification, test_connection  # noqa: E402
from app.services.settings_store import update_section  # noqa: E402

AI_BASE = "http://ai.test/v1"


@pytest.fixture(scope="module")
def db():
    with TestClient(app):
        pass
    session = get_session_factory()()
    yield session
    session.close()


@pytest.fixture
def clean_ai(db):  # noqa: ANN001, ANN201
    update_section(db, "ai", {"base_url": "", "api_key": "", "model": "", "enabled": False})
    yield
    update_section(db, "ai", {"base_url": "", "api_key": "", "model": "", "enabled": False})


@pytest.fixture
def configured_ai(db):  # noqa: ANN001, ANN201
    update_section(db, "ai", {"base_url": AI_BASE, "api_key": "sk-test", "model": "test-model"})
    yield
    update_section(db, "ai", {"base_url": "", "api_key": "", "model": "", "enabled": False})


def _make_up(db, uname: str, mid: int) -> UpUser:  # noqa: ANN001
    up = UpUser(mid=mid, uname=uname, sign=f"{uname} 的签名", followed_at="2000-01-01 00:00:00")
    db.add(up)
    db.commit()
    return up


def _ai_response(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def test_not_configured(db, clean_ai) -> None:  # noqa: ANN001
    with pytest.raises(ApiError) as excinfo:
        run_classification(db, batch_size=5)
    assert excinfo.value.code == "ai_not_configured"


@respx.mock
def test_classifies_and_creates_group(db, configured_ai) -> None:  # noqa: ANN001
    up1 = _make_up(db, "AI测试UP一", 910000001)
    up2 = _make_up(db, "AI测试UP二", 910000002)
    route = respx.post(f"{AI_BASE}/chat/completions").mock(
        return_value=_ai_response(
            '[{"mid": 910000001, "group": "技术区", "confidence": 0.9, "rationale": "科技内容"},'
            ' {"mid": 910000002, "group": "AI新分组", "confidence": 0.5, "rationale": "不明确"}]'
        )
    )
    result = run_classification(db, batch_size=10)
    assert route.called
    assert result["classified"] == 2
    assert result["created_groups"] == ["AI新分组"]
    assert db.query(GroupLocal).filter(GroupLocal.name == "AI新分组").first() is not None
    assert db.query(UpUser).filter(UpUser.mid == up1.mid).first().ai_status == "pending"
    pending = db.query(AiSuggestion).filter(AiSuggestion.up_mid == up2.mid).all()
    assert len(pending) == 1 and pending[0].status == "pending"


@respx.mock
def test_tolerates_markdown_fence(db, configured_ai) -> None:  # noqa: ANN001
    up = _make_up(db, "AI测试UP三", 910000003)
    respx.post(f"{AI_BASE}/chat/completions").mock(
        return_value=_ai_response(
            '```json\n[{"mid": 910000003, "group": "音乐", "confidence": 0.8, "rationale": "翻唱"}]\n```'
        )
    )
    result = run_classification(db, batch_size=10)
    assert result["classified"] == 1
    assert db.query(UpUser).filter(UpUser.mid == up.mid).first().ai_status == "pending"


@respx.mock
def test_http_error_marks_error(db, configured_ai) -> None:  # noqa: ANN001
    up = _make_up(db, "AI测试UP四", 910000004)
    respx.post(f"{AI_BASE}/chat/completions").mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(ApiError) as excinfo:
        run_classification(db, batch_size=10)
    assert excinfo.value.code == "ai_failed"
    assert db.query(UpUser).filter(UpUser.mid == up.mid).first().ai_status == "error"


@respx.mock
def test_invalid_json_marks_error(db, configured_ai) -> None:  # noqa: ANN001
    up = _make_up(db, "AI测试UP五", 910000005)
    respx.post(f"{AI_BASE}/chat/completions").mock(return_value=_ai_response("完全不是JSON"))
    with pytest.raises(ApiError):
        run_classification(db, batch_size=10)
    assert db.query(UpUser).filter(UpUser.mid == up.mid).first().ai_status == "error"


@respx.mock
def test_decide_accept_assigns_group(db, configured_ai) -> None:  # noqa: ANN001
    up = _make_up(db, "AI测试UP六", 910000006)
    respx.post(f"{AI_BASE}/chat/completions").mock(
        return_value=_ai_response(
            f'[{{"mid": {up.mid}, "group": "生活记录", "confidence": 0.7, "rationale": "日常"}}]'
        )
    )
    run_classification(db, batch_size=10)
    suggestion = db.query(AiSuggestion).filter(AiSuggestion.up_mid == up.mid).first()
    result = decide(db, [suggestion.id], "accept")
    assert result["decided"] == 1
    assert db.query(UpUser).filter(UpUser.mid == up.mid).first().group_id == suggestion.suggested_group_id
    assert db.query(UpUser).filter(UpUser.mid == up.mid).first().ai_status == "done"


def test_decide_reject(db) -> None:  # noqa: ANN001
    up = _make_up(db, "AI测试UP七", 910000007)
    db.add(
        AiSuggestion(
            up_mid=up.mid, suggested_group_name="随意", confidence=0.1,
            rationale="", model="m", status="pending",
        )
    )
    db.commit()
    suggestion = db.query(AiSuggestion).filter(AiSuggestion.up_mid == up.mid).first()
    decide(db, [suggestion.id], "reject")
    assert db.query(AiSuggestion).filter(AiSuggestion.id == suggestion.id).first().status == "rejected"
    with pytest.raises(ApiError):
        decide(db, [suggestion.id], "nonsense")


@respx.mock
def test_connection_ok_and_fail(db, configured_ai) -> None:  # noqa: ANN001
    respx.post(f"{AI_BASE}/chat/completions").mock(return_value=_ai_response("pong"))
    ok, message = test_connection(db)
    assert ok and "连接成功" in message
    respx.post(f"{AI_BASE}/chat/completions").mock(return_value=httpx.Response(503))
    ok, message = test_connection(db)
    assert not ok and "失败" in message
