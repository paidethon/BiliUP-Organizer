from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta
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
from app.models import AiSuggestion, GroupAlias, GroupLocal, UpUser, Video  # noqa: E402
from app.schemas import ReviewDecideIn  # noqa: E402
from app.services import memberships, taxonomy  # noqa: E402
from app.services.ai_classifier import (  # noqa: E402
    PROMPT_VERSION,
    classify_batch,
    run_classification,
    test_connection,
)
from app.services.settings_store import update_section  # noqa: E402

AI_BASE = "http://ai.test/v1"

_RESET_AI = {
    "base_url": "",
    "api_key": "",
    "model": "",
    "enabled": False,
    "grouping_instructions": "",
    "auto_apply_enabled": False,
    "auto_apply_threshold": 0.9,
    "review_threshold": 0.65,
    "allow_new_categories": False,
}


@pytest.fixture(scope="module")
def db():
    with TestClient(app):
        pass
    session = get_session_factory()()
    yield session
    session.close()


@pytest.fixture
def clean_ai(db):  # noqa: ANN001, ANN201
    update_section(db, "ai", dict(_RESET_AI))
    yield
    update_section(db, "ai", dict(_RESET_AI))


@pytest.fixture
def configured_ai(db):  # noqa: ANN001, ANN201
    """AI configured with group creation allowed and the default thresholds."""
    update_section(
        db,
        "ai",
        {
            "base_url": AI_BASE,
            "api_key": "sk-test",
            "model": "test-model",
            "allow_new_categories": True,
            "review_threshold": 0.65,
            "auto_apply_threshold": 0.9,
        },
    )
    yield
    update_section(db, "ai", dict(_RESET_AI))


def _make_up(db, uname: str, mid: int) -> UpUser:  # noqa: ANN001
    """watched_count=1 keeps new UPs out of the weekly-report test's top-10
    never-watched cutoff (the report test shares this database module-wide)."""
    up = UpUser(
        mid=mid,
        uname=uname,
        sign=f"{uname} 的签名",
        followed_at="2000-01-01 00:00:00",
        watched_count=1,
    )
    db.add(up)
    db.commit()
    return up


def _ai_response(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


def _suggestion(db, mid: int) -> AiSuggestion:  # noqa: ANN001
    return db.query(AiSuggestion).filter(AiSuggestion.up_mid == mid).order_by(AiSuggestion.id.desc()).first()


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
            '[{"mid": 910000001, "group": "历史人文", "confidence": 0.9, "rationale": "历史内容"},'
            ' {"mid": 910000002, "group": "AI新分组", "confidence": 0.7, "rationale": "不明确"}]'
        )
    )
    result = run_classification(db, batch_size=2)
    assert route.called
    assert result["classified"] == 2
    assert result["needs_review"] == 2
    assert result["created_groups"] == ["历史人文", "AI新分组"]
    assert db.query(GroupLocal).filter(GroupLocal.name == "AI新分组").first() is not None
    assert db.query(UpUser).filter(UpUser.mid == up1.mid).first().ai_status == "pending"
    suggestion = _suggestion(db, up2.mid)
    assert suggestion is not None and suggestion.status == "pending"


@respx.mock
def test_tolerates_markdown_fence(db, configured_ai) -> None:  # noqa: ANN001
    up = _make_up(db, "AI测试UP三", 910000003)
    respx.post(f"{AI_BASE}/chat/completions").mock(
        return_value=_ai_response(
            '```json\n[{"mid": 910000003, "group": "音乐", "confidence": 0.8, "rationale": "翻唱"}]\n```'
        )
    )
    result = run_classification(db, batch_size=1)
    assert result["classified"] == 1
    assert db.query(UpUser).filter(UpUser.mid == up.mid).first().ai_status == "pending"


@respx.mock
def test_compact_keys_and_tags_landed(db, configured_ai) -> None:  # noqa: ANN001
    up = _make_up(db, "AI测试UP标签", 910000013)
    long_tag = "x" * 20
    respx.post(f"{AI_BASE}/chat/completions").mock(
        return_value=_ai_response(
            json.dumps(
                [
                    {
                        "m": up.mid,
                        "g": "历史人文二",
                        "t": ["  机器人 ", "机器人", long_tag, "游戏", "数码", "音乐", "影视"],
                        "c": 0.75,
                        "r": "测试理由",
                    }
                ],
                ensure_ascii=False,
            )
        )
    )
    result = run_classification(db, batch_size=1)
    assert result["classified"] == 1
    suggestion = _suggestion(db, up.mid)
    assert json.loads(suggestion.suggested_tags) == ["机器人", "x" * 16, "游戏", "数码", "音乐"]
    assert suggestion.prompt_version == PROMPT_VERSION


@respx.mock
def test_alias_resolution_reuses_existing_group(db, configured_ai) -> None:  # noqa: ANN001
    up = _make_up(db, "AI测试UP别名", 910000014)
    demo_group = db.query(GroupLocal).filter(GroupLocal.name == "科技数码").first()
    assert demo_group is not None, "demo taxonomy must be seeded"
    respx.post(f"{AI_BASE}/chat/completions").mock(
        return_value=_ai_response(
            f'[{{"mid": {up.mid}, "group": "科技区", "confidence": 0.8, "rationale": "数码内容"}}]'
        )
    )
    run_classification(db, batch_size=1)
    suggestion = _suggestion(db, up.mid)
    assert suggestion.suggested_group_id == demo_group.id
    alias = db.query(GroupAlias).filter(GroupAlias.alias == "科技区").first()
    assert alias is not None and alias.group_id == demo_group.id


@respx.mock
def test_allow_new_false_keeps_raw_name_pending(db, configured_ai) -> None:  # noqa: ANN001
    update_section(db, "ai", {"allow_new_categories": False})
    up = _make_up(db, "AI测试UP禁建", 910000015)
    respx.post(f"{AI_BASE}/chat/completions").mock(
        return_value=_ai_response(
            f'[{{"mid": {up.mid}, "group": "绝不存在的分组XYZ", "confidence": 0.9, "rationale": "猜测"}}]'
        )
    )
    run_classification(db, batch_size=1)
    suggestion = _suggestion(db, up.mid)
    assert suggestion.suggested_group_id is None
    assert suggestion.suggested_group_name == "绝不存在的分组XYZ"
    assert suggestion.status == "pending"
    assert db.query(GroupLocal).filter(GroupLocal.name == "绝不存在的分组XYZ").first() is None
    update_section(db, "ai", {"allow_new_categories": True})


@respx.mock
def test_confidence_workflow_three_tiers(db, configured_ai) -> None:  # noqa: ANN001
    up_apply = _make_up(db, "AI测试UP高置信", 910000016)
    up_review = _make_up(db, "AI测试UP中置信", 910000017)
    up_low = _make_up(db, "AI测试UP低置信", 910000018)
    taxonomy.set_status_labels(db, up_apply.mid, ["待整理"], source="manual")
    demo_group = db.query(GroupLocal).filter(GroupLocal.name == "科技数码").first()
    respx.post(f"{AI_BASE}/chat/completions").mock(
        return_value=_ai_response(
            json.dumps(
                [
                    {
                        "mid": up_apply.mid,
                        "group": "科技数码",
                        "tags": ["数码", "DIY"],
                        "c": 0.95,
                        "r": "明确",
                    },
                    {"mid": up_review.mid, "group": "历史人文三", "c": 0.8, "r": "尚可"},
                    {"mid": up_low.mid, "group": "历史人文三", "c": 0.3, "r": "说不准"},
                ]
            )
        )
    )
    result = classify_batch(db, [up_apply.mid, up_review.mid, up_low.mid], auto_apply=True, threshold=0.9)
    assert result["classified"] == 2 and result["auto_applied"] == 1
    assert result["needs_review"] == 1 and result["unclassifiable"] == 1 and result["failed"] == 0

    applied = db.query(UpUser).filter(UpUser.mid == up_apply.mid).first()
    assert applied.group_id == demo_group.id
    assert applied.ai_status == "done"
    assert demo_group.id in memberships.group_ids_of(db, up_apply.mid)
    assert {t.name for t in taxonomy.tags_of(db, up_apply.mid)} == {"数码", "DIY"}
    # 待整理 was cleared by the successful auto-apply
    assert "待整理" not in taxonomy.status_labels_of(db, up_apply.mid)
    applied_suggestion = _suggestion(db, up_apply.mid)
    assert applied_suggestion.status == "accepted" and applied_suggestion.decided_at is not None

    review_suggestion = _suggestion(db, up_review.mid)
    assert review_suggestion.status == "pending"
    assert db.query(UpUser).filter(UpUser.mid == up_review.mid).first().ai_status == "pending"

    low_suggestion = _suggestion(db, up_low.mid)
    assert low_suggestion.status == "unclassifiable"
    assert db.query(UpUser).filter(UpUser.mid == up_low.mid).first().ai_status == "done"
    assert "待整理" in taxonomy.status_labels_of(db, up_low.mid)


@respx.mock
def test_unclassifiable_answer_marks_pending_tidy(db, configured_ai) -> None:  # noqa: ANN001
    up = _make_up(db, "AI测试UP无法确定", 910000019)
    respx.post(f"{AI_BASE}/chat/completions").mock(
        return_value=_ai_response(f'[{{"mid": {up.mid}, "group": "无法确定", "c": 0.99, "r": "看不出来"}}]')
    )
    result = classify_batch(db, [up.mid])
    assert result["unclassifiable"] == 1 and result["classified"] == 0
    suggestion = _suggestion(db, up.mid)
    assert suggestion.status == "unclassifiable" and suggestion.suggested_group_name == ""
    assert "待整理" in taxonomy.status_labels_of(db, up.mid)


@respx.mock
def test_previous_group_name_captured(db, configured_ai) -> None:  # noqa: ANN001
    up = _make_up(db, "AI测试UP原组", 910000020)
    old_group = GroupLocal(name="旧分组此前")
    db.add(old_group)
    db.flush()
    memberships.add_membership(db, up, old_group.id)
    db.commit()
    respx.post(f"{AI_BASE}/chat/completions").mock(
        return_value=_ai_response(f'[{{"mid": {up.mid}, "group": "历史人文四", "c": 0.8, "r": "变化"}}]')
    )
    run_classification(db, batch_size=1)
    assert _suggestion(db, up.mid).previous_group_name == "旧分组此前"


@respx.mock
def test_no_group_cap_creates_more_than_twenty(db, configured_ai) -> None:  # noqa: ANN001
    names = list("天地玄黄宇宙洪荒日月山川火水风雷金木土龙凤麒麟夏商周"[:25])
    ups = [_make_up(db, f"AI测试UP量产{i}", 910000100 + i) for i in range(len(names))]
    payload = [{"mid": ups[i].mid, "group": name, "c": 0.8, "r": "独立分组"} for i, name in enumerate(names)]
    respx.post(f"{AI_BASE}/chat/completions").mock(
        return_value=_ai_response(json.dumps(payload, ensure_ascii=False))
    )
    result = run_classification(db, batch_size=len(ups))
    assert sorted(result["created_groups"]) == sorted(names)
    for name in names:
        assert db.query(GroupLocal).filter(GroupLocal.name == name).first() is not None


@respx.mock
def test_prompt_has_relative_time_labels(db, configured_ai) -> None:  # noqa: ANN001
    up = _make_up(db, "AI测试UP时间", 910000130)
    pubdate = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    db.add(
        Video(
            bvid="BV1reltime001",
            up_mid=up.mid,
            title="相对时间标注测试",
            pubdate=pubdate,
        )
    )
    db.commit()
    route = respx.post(f"{AI_BASE}/chat/completions").mock(
        return_value=_ai_response(f'[{{"mid": {up.mid}, "group": "游戏", "c": 0.8, "r": "游戏"}}]')
    )
    run_classification(db, batch_size=1)
    body = json.loads(route.calls.last.request.content)
    prompt = body["messages"][1]["content"]
    assert "3天前:相对时间标注测试" in prompt
    assert "越靠前越新" in body["messages"][0]["content"]


@respx.mock
def test_evidence_structured_and_secret_free(db, configured_ai) -> None:  # noqa: ANN001
    up = _make_up(db, "AI测试UP证据", 910000131)
    db.add(
        Video(
            bvid="BV1evidence01",
            up_mid=up.mid,
            title="证据样本标题一",
            pubdate=(datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"),
        )
    )
    db.commit()
    respx.post(f"{AI_BASE}/chat/completions").mock(
        return_value=_ai_response(f'[{{"mid": {up.mid}, "group": "音乐", "c": 0.8, "r": "音乐"}}]')
    )
    run_classification(db, batch_size=1)
    suggestion = _suggestion(db, up.mid)
    evidence = json.loads(suggestion.evidence)
    assert set(evidence) == {"video_count", "source", "sample_titles"}
    assert evidence["video_count"] == 1
    assert evidence["source"] == "db_cache"
    assert evidence["sample_titles"] == ["证据样本标题一"]
    assert suggestion.provider == "ai.test" and suggestion.prompt_version == PROMPT_VERSION
    raw = suggestion.evidence + json.dumps(suggestion.suggested_tags)
    for secret in ("sk-test", "api_key", "cookie", "Authorization", "SESSDATA"):
        assert secret not in raw


@respx.mock
def test_read_timeout_retries_once(db, configured_ai) -> None:  # noqa: ANN001
    up = _make_up(db, "AI测试UP八", 910000008)
    route = respx.post(f"{AI_BASE}/chat/completions").mock(
        side_effect=[
            httpx.ReadTimeout("The read operation timed out"),
            _ai_response(
                f'[{{"mid": {up.mid}, "group": "游戏", "confidence": 0.8, "rationale": "游戏实况"}}]'
            ),
        ]
    )
    result = run_classification(db, batch_size=1)
    assert route.call_count == 2
    assert result["classified"] == 1


@respx.mock
def test_flattens_nested_group_format(db, configured_ai) -> None:  # noqa: ANN001
    up1 = _make_up(db, "AI测试UP九", 910000009)
    up2 = _make_up(db, "AI测试UP十", 910000010)
    respx.post(f"{AI_BASE}/chat/completions").mock(
        return_value=_ai_response(
            '[{"group": "绘画动画", "ups": [{"mid": 910000009, "c": 0.8}, {"mid": 910000010, "c": 0.8}]}]'
        )
    )
    result = run_classification(db, batch_size=2)
    assert result["classified"] == 2
    assert db.query(UpUser).filter(UpUser.mid == up1.mid).first().ai_status == "pending"
    assert db.query(UpUser).filter(UpUser.mid == up2.mid).first().ai_status == "pending"


@respx.mock
def test_http_error_marks_error(db, configured_ai) -> None:  # noqa: ANN001
    up = _make_up(db, "AI测试UP四", 910000004)
    respx.post(f"{AI_BASE}/chat/completions").mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(ApiError) as excinfo:
        run_classification(db, batch_size=1)
    assert excinfo.value.code == "ai_failed"
    assert db.query(UpUser).filter(UpUser.mid == up.mid).first().ai_status == "error"


@respx.mock
def test_invalid_json_marks_error(db, configured_ai) -> None:  # noqa: ANN001
    up = _make_up(db, "AI测试UP五", 910000005)
    respx.post(f"{AI_BASE}/chat/completions").mock(return_value=_ai_response("完全不是JSON"))
    # batch of 2: the pick also includes the UP left in error by the previous
    # test (smaller mid), and the failure path must mark the whole batch
    with pytest.raises(ApiError):
        run_classification(db, batch_size=2)
    assert db.query(UpUser).filter(UpUser.mid == up.mid).first().ai_status == "error"


class _Admin:
    username = "tester"


def test_decide_accept_assigns_group(db) -> None:  # noqa: ANN001
    from app.api.review_routes import decide as decide_route

    up = _make_up(db, "AI测试UP六", 910000006)
    up.ai_status = "pending"
    group = GroupLocal(name="决策已存在组")
    db.add(group)
    db.flush()
    suggestion = AiSuggestion(
        up_mid=up.mid,
        suggested_group_id=group.id,
        suggested_group_name=group.name,
        suggested_tags=json.dumps(["决策标签"], ensure_ascii=False),
        confidence=0.7,
        model="m",
        status="pending",
    )
    db.add(suggestion)
    db.commit()
    result = decide_route(ReviewDecideIn(ids=[suggestion.id], decision="accept"), _Admin(), db)
    assert result["applied"] == 1
    row = db.query(UpUser).filter(UpUser.mid == up.mid).first()
    assert row.group_id == group.id and row.ai_status == "done"
    assert group.id in memberships.group_ids_of(db, up.mid)
    assert {t.name for t in taxonomy.tags_of(db, up.mid)} == {"决策标签"}
    assert db.query(AiSuggestion).filter(AiSuggestion.id == suggestion.id).first().status == "accepted"


def test_decide_accept_creates_missing_group(db) -> None:  # noqa: ANN001
    from app.api.review_routes import decide as decide_route

    up = _make_up(db, "AI测试UP建组", 910000021)
    up.ai_status = "pending"
    suggestion = AiSuggestion(
        up_mid=up.mid,
        suggested_group_id=None,
        suggested_group_name="决策新建组",
        confidence=0.7,
        model="m",
        status="pending",
    )
    db.add(suggestion)
    db.commit()
    decide_route(ReviewDecideIn(ids=[suggestion.id], decision="accept"), _Admin(), db)
    created = db.query(GroupLocal).filter(GroupLocal.name == "决策新建组").first()
    assert created is not None
    row = db.query(UpUser).filter(UpUser.mid == up.mid).first()
    assert row.group_id == created.id and row.ai_status == "done"


def test_decide_unclassifiable_marks_tidy(db) -> None:  # noqa: ANN001
    from app.api.review_routes import decide as decide_route

    up = _make_up(db, "AI测试UP判难", 910000022)
    up.ai_status = "pending"
    suggestion = AiSuggestion(
        up_mid=up.mid,
        suggested_group_name="说不准的组",
        confidence=0.5,
        model="m",
        status="pending",
    )
    db.add(suggestion)
    db.commit()
    decide_route(ReviewDecideIn(ids=[suggestion.id], decision="unclassifiable"), _Admin(), db)
    row = db.query(UpUser).filter(UpUser.mid == up.mid).first()
    assert row.ai_status == "done"
    assert "待整理" in taxonomy.status_labels_of(db, up.mid)
    assert db.query(AiSuggestion).filter(AiSuggestion.id == suggestion.id).first().status == "unclassifiable"


def test_decide_reject_and_invalid(db) -> None:  # noqa: ANN001
    from app.api.review_routes import decide as decide_route

    up = _make_up(db, "AI测试UP七", 910000007)
    up.ai_status = "pending"
    db.add(
        AiSuggestion(
            up_mid=up.mid,
            suggested_group_name="随意",
            confidence=0.1,
            rationale="",
            model="m",
            status="pending",
        )
    )
    db.commit()
    suggestion = db.query(AiSuggestion).filter(AiSuggestion.up_mid == up.mid).first()
    decide_route(ReviewDecideIn(ids=[suggestion.id], decision="reject"), _Admin(), db)
    assert db.query(AiSuggestion).filter(AiSuggestion.id == suggestion.id).first().status == "rejected"
    with pytest.raises(ApiError):
        decide_route(ReviewDecideIn(ids=[suggestion.id], decision="nonsense"), _Admin(), db)


@respx.mock
def test_connection_ok_and_fail(db, configured_ai) -> None:  # noqa: ANN001
    respx.post(f"{AI_BASE}/chat/completions").mock(return_value=_ai_response("pong"))
    ok, message = test_connection(db)
    assert ok and "连接成功" in message
    respx.post(f"{AI_BASE}/chat/completions").mock(return_value=httpx.Response(503))
    ok, message = test_connection(db)
    assert not ok and "失败" in message
