"""AI classification: suggest a local group for each UP via an
OpenAI-compatible chat completions endpoint. Owned by the main agent after the
AI subagent hit the concurrency limit; kept to the frozen contract in the
original stub docstring.
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import AiSuggestion, GroupLocal, UpUser, Video
from app.services.settings_store import get_section_raw
from app.util import utcnow

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "你是B站关注列表整理助手。根据UP主的昵称、签名和最近视频标题，"
    "把每个UP分入最合适的分组。优先使用已有分组；确实不适合时才建议新分组。"
    "只输出一个JSON数组，不要输出任何其他文字，"
    '格式：[{"mid":123,"group":"分组名","confidence":0.85,"rationale":"一句话理由"}]'
)


def _ai_config(db: Session) -> dict[str, Any]:
    cfg = get_section_raw(db, "ai")
    if not cfg.get("base_url") or not cfg.get("api_key") or not cfg.get("model"):
        raise ApiError(400, "ai_not_configured", "AI 服务未配置：请先在设置页填写 Base URL、API Key 与模型名")
    return cfg


def _pick_ups(db: Session, batch_size: int) -> list[UpUser]:
    return (
        db.query(UpUser)
        .filter(UpUser.ai_status.in_(("none", "error")), UpUser.missing.is_(False))
        .order_by(UpUser.followed_at.asc(), UpUser.mid.asc())
        .limit(batch_size)
        .all()
    )


def _recent_titles(db: Session, mids: list[int]) -> dict[int, list[str]]:
    if not mids:
        return {}
    rows = (
        db.query(Video.up_mid, Video.title, Video.pubdate)
        .filter(Video.up_mid.in_(mids))
        .order_by(Video.up_mid.asc(), Video.pubdate.desc())
        .all()
    )
    titles: dict[int, list[str]] = {}
    for up_mid, title, _pubdate in rows:
        bucket = titles.setdefault(up_mid, [])
        if len(bucket) < 3 and title:
            bucket.append(title)
    return titles


def _build_prompt(ups: list[UpUser], group_names: list[str], titles: dict[int, list[str]]) -> str:
    lines = [f"已有分组：{json.dumps(group_names, ensure_ascii=False)}", "UP主列表："]
    for up in ups:
        entry = {"mid": up.mid, "uname": up.uname, "sign": (up.sign or "")[:80]}
        if titles.get(up.mid):
            entry["recent_videos"] = titles[up.mid]
        lines.append(json.dumps(entry, ensure_ascii=False))
    lines.append("请输出JSON数组。")
    return "\n".join(lines)


def _parse_items(content: str) -> list[dict[str, Any]]:
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        raise ValueError("response does not contain a JSON array")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, list):
        raise ValueError("response is not a JSON array")
    return [item for item in parsed if isinstance(item, dict)]


def _chat(base_url: str, api_key: str, model: str, prompt: str) -> str:
    resp = httpx.post(
        base_url.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return str(data["choices"][0]["message"]["content"])


def _ensure_group(db: Session, name: str) -> GroupLocal:
    group = db.query(GroupLocal).filter(GroupLocal.name == name).first()
    if group is None:
        group = GroupLocal(name=name[:64])
        db.add(group)
        db.flush()
    return group


def run_classification(db: Session, batch_size: int = 20) -> dict:
    cfg = _ai_config(db)
    ups = _pick_ups(db, batch_size)
    if not ups:
        return {"classified": 0, "pending": 0, "created_groups": []}

    group_names = [g.name for g in db.query(GroupLocal).order_by(GroupLocal.sort_order).all()]
    titles = _recent_titles(db, [up.mid for up in ups])
    prompt = _build_prompt(ups, group_names, titles)

    try:
        content = _chat(cfg["base_url"], cfg["api_key"], cfg["model"], prompt)
        items = _parse_items(content)
    except (httpx.HTTPError, ValueError, KeyError, json.JSONDecodeError) as exc:
        for up in ups:
            up.ai_status = "error"
        db.commit()
        log.warning("ai classification failed: %s", exc)
        raise ApiError(502, "ai_failed", f"AI 调用或解析失败：{exc}") from exc

    valid_mids = {up.mid for up in ups}
    known_groups = set(group_names)
    created_groups: list[str] = []
    classified = 0
    for item in items:
        try:
            mid = int(item.get("mid"))
        except (TypeError, ValueError):
            continue
        if mid not in valid_mids:
            continue
        name = str(item.get("group") or "").strip()[:64]
        if not name:
            continue
        group = _ensure_group(db, name)
        if name not in known_groups:
            created_groups.append(name)
            known_groups.add(name)
        try:
            confidence = max(0.0, min(1.0, float(item.get("confidence", 0))))
        except (TypeError, ValueError):
            confidence = 0.0
        db.add(
            AiSuggestion(
                up_mid=mid,
                suggested_group_id=group.id,
                suggested_group_name=group.name,
                confidence=confidence,
                rationale=str(item.get("rationale") or "")[:500],
                model=str(cfg["model"]),
                status="pending",
            )
        )
        up = db.query(UpUser).filter(UpUser.mid == mid).first()
        if up is not None:
            up.ai_status = "pending"
        classified += 1
    db.commit()
    pending = db.query(AiSuggestion).filter(AiSuggestion.status == "pending").count()
    return {"classified": classified, "pending": pending, "created_groups": created_groups}


def decide(db: Session, ids: list[int], decision: str) -> dict:
    if decision not in ("accept", "reject"):
        raise ApiError(400, "bad_request", "decision 必须是 accept 或 reject")
    rows = (
        db.query(AiSuggestion)
        .filter(AiSuggestion.id.in_(ids), AiSuggestion.status == "pending")
        .all()
    )
    applied = 0
    for row in rows:
        row.status = "accepted" if decision == "accept" else "rejected"
        row.decided_at = utcnow()
        if decision == "accept" and row.suggested_group_id:
            up = db.query(UpUser).filter(UpUser.mid == row.up_mid).first()
            if up is not None:
                up.group_id = row.suggested_group_id
                up.ai_status = "done"
                applied += 1
    db.commit()
    return {"decided": len(rows), "applied": applied}


def test_connection(db: Session) -> tuple[bool, str]:
    try:
        cfg = _ai_config(db)
    except ApiError as exc:
        return False, exc.message
    try:
        content = _chat(cfg["base_url"], cfg["api_key"], cfg["model"], "回复 pong")
    except httpx.HTTPError as exc:
        return False, f"连接失败：{exc}"
    except (KeyError, ValueError) as exc:
        return False, f"响应格式异常：{exc}"
    return True, f"连接成功（模型 {cfg['model']}，回复 {content[:20]}）"
