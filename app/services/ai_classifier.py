"""AI classification: suggest a local group for each UP via an
OpenAI-compatible chat completions endpoint. Owned by the main agent after the
AI subagent hit the concurrency limit; kept to the frozen contract in the
original stub docstring.

Token strategy (batches are strictly serial by design):
- one single-turn request per batch, always the same byte-identical system
  prompt and a stable "已有分组" prefix, so provider-side prefix caching kicks
  in across consecutive batches;
- a compact pipe payload (no JSON quotes/braces) with top-10 truncated video
  titles + 分区, which classify far better than raw JSON lines at ~1/4 the
  tokens;
- a module lock so batches never overlap — each chat completes before the
  next one starts.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import AiSuggestion, GroupLocal, UpUser, Video
from app.services.settings_store import get_section_raw
from app.util import utcnow

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "你是B站关注列表整理助手。把每个UP按内容分入最合适的一个分组，优先使用已有分组；"
    "确实不合适才建议新分组。只输出JSON数组，禁止任何其他文字："
    '[{"m":mid,"g":"分组","c":0.85,"r":"理由(≤12字)"}]'
)

_CHAT_LOCK = threading.Lock()

# Non-thinking mode saves the dominant token share (reasoning output was
# 2-4k tokens per batch); providers that reject the extension get their
# requests downgraded automatically (see _chat).
_EXTRA_BODY: dict[str, Any] = {"enable_thinking": False}

# Reasoning models routinely spend well over 30s per 20-UP batch, so the read
# budget is generous; only the connect phase stays tight.
_CHAT_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)


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
        db.query(Video.up_mid, Video.title, Video.tname, Video.pubdate)
        .filter(Video.up_mid.in_(mids))
        .order_by(Video.up_mid.asc(), Video.pubdate.desc())
        .all()
    )
    titles: dict[int, list[str]] = {}
    for up_mid, title, tname, _pubdate in rows:
        bucket = titles.setdefault(up_mid, [])
        if len(bucket) >= 10 or not title:
            continue
        entry = title[:20]
        if tname:
            entry += f"[{tname[:6]}]"
        bucket.append(entry)
    return titles


def _ensure_video_data(db: Session, ups: list[UpUser]) -> None:
    """Fetch top uploads for UPs with no cached videos (accurate 分区/标题)."""
    from app.services.bilibili.cookies import load_cookies
    from app.services.bilibili.followings import fetch_recent_archives

    missing = [up.mid for up in ups if not _recent_titles(db, [up.mid]).get(up.mid)]
    if missing and load_cookies(db):
        try:
            refreshed = fetch_recent_archives(db, missing, per_up=10, max_ups=len(missing))
            log.info("fetched archives for %d/%d unclassified UPs", refreshed, len(missing))
        except Exception:  # noqa: BLE001 - classification proceeds on cached data
            log.exception("archive prefetch failed; classifying without video data")


def _build_prompt(ups: list[UpUser], group_names: list[str], titles: dict[int, list[str]]) -> str:
    lines = [f"已有分组：{'、'.join(group_names)}", "UP列表（mid|昵称|签名|最近视频 标题[分区]，最多10条）："]
    for up in ups:
        sign = (up.sign or "").replace("|", "／")[:60]
        videos = ";".join(titles.get(up.mid) or []) or "无投稿记录"
        uname = (up.uname or "").replace("|", "／")
        lines.append(f"{up.mid}|{uname}|{sign}|{videos}")
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
    items: list[dict[str, Any]] = []
    for raw in parsed:
        if not isinstance(raw, dict):
            continue
        item: dict[str, Any] = dict(raw)
        # compact keys (m/g/c/r) normalize onto the canonical names
        if "m" in item and "mid" not in item:
            item["mid"] = item["m"]
        if "g" in item and "group" not in item:
            item["group"] = item["g"]
        if "c" in item and "confidence" not in item:
            item["confidence"] = item["c"]
        if "r" in item and "rationale" not in item:
            item["rationale"] = item["r"]
        items.append(item)
    # Models occasionally ignore the flat format and answer
    # [{"group": "...", "ups": [{"mid": ...}, ...]}]; flatten so the run still counts.
    flat: list[dict[str, Any]] = []
    for item in items:
        ups = item.get("ups")
        if isinstance(ups, list) and item.get("group"):
            flat.extend({**up, "group": item["group"]} for up in ups if isinstance(up, dict))
        else:
            flat.append(item)
    return flat


def _chat(base_url: str, api_key: str, model: str, prompt: str, system: str | None = None) -> str:
    last_exc: Exception | None = None
    with _CHAT_LOCK:  # one conversation at a time keeps provider cache hits high
        for _attempt in range(2):
            try:
                payload: dict[str, Any] = {
                    "model": model,
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": system or _SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                }
                payload.update(_EXTRA_BODY)
                resp = httpx.post(
                    base_url.rstrip("/") + "/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                    timeout=_CHAT_TIMEOUT,
                )
                if resp.status_code == 400 and _EXTRA_BODY:
                    _EXTRA_BODY.clear()  # provider rejected the extension params
                    payload = {k: v for k, v in payload.items() if k not in {"enable_thinking"}}
                    resp = httpx.post(
                        base_url.rstrip("/") + "/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json=payload,
                        timeout=_CHAT_TIMEOUT,
                    )
                resp.raise_for_status()
                data = resp.json()
                return str(data["choices"][0]["message"]["content"])
            except httpx.ReadTimeout as exc:
                last_exc = exc
    assert last_exc is not None
    raise last_exc


def _ensure_group(db: Session, name: str) -> GroupLocal:
    group = db.query(GroupLocal).filter(GroupLocal.name == name).first()
    if group is None:
        group = GroupLocal(name=name[:64])
        db.add(group)
        db.flush()
    return group


def run_classification(db: Session, batch_size: int = 20, instruction: str = "") -> dict:
    cfg = _ai_config(db)
    ups = _pick_ups(db, batch_size)
    if not ups:
        return {"classified": 0, "pending": 0, "created_groups": []}

    _ensure_video_data(db, ups)
    group_names = [g.name for g in db.query(GroupLocal).order_by(GroupLocal.sort_order).all()]
    titles = _recent_titles(db, [up.mid for up in ups])
    prompt = _build_prompt(ups, group_names, titles)
    if instruction:
        # appended at the END so the cached prefix (system + group list + UP
        # rows) stays byte-stable across batches with different instructions
        prompt += "\n补充要求：" + instruction.strip()[:300]

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
    rows = db.query(AiSuggestion).filter(AiSuggestion.id.in_(ids), AiSuggestion.status == "pending").all()
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
