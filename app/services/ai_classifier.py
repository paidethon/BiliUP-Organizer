"""AI classification: suggest a local category + content tags for each UP via
an OpenAI-compatible chat completions endpoint.

Token strategy (batches are strictly serial by design):
- one single-turn request per batch, always the same byte-identical system
  prompt and a stable "已有分组" prefix, so provider-side prefix caching kicks
  in across consecutive batches; the free-form instruction is appended at the
  very END for the same reason;
- a compact pipe payload (no JSON quotes/braces) with relative-time annotated
  video titles (newest first), which classify far better than raw JSON lines;
- a module lock so batches never overlap — each chat completes before the
  next one starts.

Confidence workflow (thresholds come from the ai settings section):
- c >= threshold with auto_apply -> applied directly (primary group +
  membership + tags), suggestion recorded as accepted;
- review_threshold <= c < threshold, or auto_apply off -> suggestion pending
  human review;
- c < review_threshold, or the model answers 无法确定 -> unclassifiable, the
  UP gets the 待整理 status label instead of a guess.

Local categories are NOT capped: bilibili's 20-native-tag limit only applies
to native tags, not to groups_local rows (taxonomy.ensure_group is policy).
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import AiSuggestion, GroupLocal, UpUser, Video
from app.services import memberships, taxonomy
from app.services.settings_store import get_section_raw
from app.util import utcnow

log = logging.getLogger(__name__)

PROMPT_VERSION = "v2"

_SYSTEM_PROMPT = (
    "你是B站关注列表整理助手。把每个UP按内容分入最合适的一个分组，优先使用已有分组；"
    '确实不合适才建议新分组；判断不了就把 g 输出为"无法确定"。'
    "同时给每个UP挑0-5个最能概括内容方向的标签。"
    "UP的投稿按时间倒序排列，越靠前越新：最近内容权重更高，若近期主题与历史不同以近期为准。"
    "只输出JSON数组，禁止任何其他文字："
    '[{"m":mid,"g":"分组","t":["标签1","标签2"],"c":0.94,"r":"简短理由≤20字"}]'
)

_CHAT_LOCK = threading.Lock()

# Non-thinking mode saves the dominant token share (reasoning output was
# 2-4k tokens per batch); providers that reject the extension get their
# requests downgraded automatically (see _chat).
_EXTRA_BODY: dict[str, Any] = {"enable_thinking": False}

# Reasoning models routinely spend well over 30s per 20-UP batch, so the read
# budget is generous; only the connect phase stays tight.
_CHAT_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)

_UNCLASSIFIABLE = "无法确定"


def _ai_config(db: Session) -> dict[str, Any]:
    cfg = get_section_raw(db, "ai")
    if not cfg.get("base_url") or not cfg.get("api_key") or not cfg.get("model"):
        raise ApiError(400, "ai_not_configured", "AI 服务未配置：请先在设置页填写 Base URL、API Key 与模型名")
    return cfg


def _float_cfg(cfg: dict[str, Any], key: str, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(cfg.get(key, default))))
    except (TypeError, ValueError):
        return default


def pick_up_mids(db: Session, batch_size: int) -> list[int]:
    """Next UPs to classify: not missing, never successfully classified."""
    rows = (
        db.query(UpUser.mid)
        .filter(UpUser.ai_status.in_(("none", "error")), UpUser.missing.is_(False))
        .order_by(UpUser.followed_at.asc(), UpUser.mid.asc())
        .limit(batch_size)
        .all()
    )
    return [row[0] for row in rows]


def _relative_time(pubdate: str | None, now: datetime) -> str | None:
    """Coarse age label for the prompt (3天前 / 2个月前 / 1年前)."""
    if not pubdate:
        return None
    try:
        dt = datetime.strptime(pubdate.strip()[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    seconds = max(0.0, (now - dt).total_seconds())
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{int(seconds // 60)}分钟前"
    if seconds < 86400:
        return f"{int(seconds // 3600)}小时前"
    days = seconds / 86400
    if days < 30:
        return f"{int(days)}天前"
    if days < 365:
        return f"{int(days // 30)}个月前"
    return f"{int(days // 365)}年前"


def _video_counts(db: Session, mids: list[int]) -> dict[int, int]:
    if not mids:
        return {}
    rows = (
        db.query(Video.up_mid, func.count(Video.id))
        .filter(Video.up_mid.in_(mids))
        .group_by(Video.up_mid)
        .all()
    )
    return {mid: count for mid, count in rows}


def _video_data(db: Session, mids: list[int], now: datetime) -> dict[int, dict[str, Any]]:
    """One IN query, then per-UP: prompt lines (top 10, newest first, with
    relative timestamps), evidence samples (top 3 titles) and upload count."""
    data: dict[int, dict[str, Any]] = {mid: {"count": 0, "lines": [], "samples": []} for mid in mids}
    if not mids:
        return data
    rows = (
        db.query(Video.up_mid, Video.title, Video.tname, Video.pubdate)
        .filter(Video.up_mid.in_(mids))
        .order_by(Video.up_mid.asc(), Video.pubdate.desc())
        .all()
    )
    for up_mid, title, tname, pubdate in rows:
        bucket = data.setdefault(up_mid, {"count": 0, "lines": [], "samples": []})
        bucket["count"] += 1
        if not title or len(bucket["lines"]) >= 10:
            continue
        rel = _relative_time(pubdate, now)
        entry = f"{rel}:{title[:20]}" if rel else title[:20]
        if tname:
            entry += f"[{tname[:6]}]"
        bucket["lines"].append(entry)
        if len(bucket["samples"]) < 3:
            bucket["samples"].append(title[:20])
    return data


def _fetch_missing_archives(db: Session, mids: list[int]) -> set[int]:
    """Fetch top uploads for UPs with no cached videos. Returns the mids a
    fetch was attempted for — evidence provenance only, never credentials."""
    counts = _video_counts(db, mids)
    missing = [mid for mid in mids if not counts.get(mid)]
    if not missing:
        return set()
    from app.services.bilibili.cookies import load_cookies
    from app.services.bilibili.followings import fetch_recent_archives

    if not load_cookies(db):
        return set()
    try:
        refreshed = fetch_recent_archives(db, missing, per_up=10, max_ups=len(missing))
        log.info("fetched archives for %d/%d unclassified UPs", refreshed, len(missing))
    except Exception:  # noqa: BLE001 - classification proceeds on cached data
        log.exception("archive prefetch failed; classifying without video data")
        return set()
    return set(missing)


def _previous_group_names(db: Session, ups: list[UpUser]) -> dict[int, str | None]:
    """Primary category at classification time, for change detection."""
    group_ids = {up.group_id for up in ups if up.group_id is not None}
    names: dict[int, str] = {}
    if group_ids:
        rows = db.query(GroupLocal.id, GroupLocal.name).filter(GroupLocal.id.in_(group_ids)).all()
        names = {gid: name for gid, name in rows}
    return {up.mid: names.get(up.group_id) for up in ups}


def _build_prompt(ups: list[UpUser], group_names: list[str], video_data: dict[int, dict[str, Any]]) -> str:
    lines = [
        f"已有分组：{'、'.join(group_names)}",
        "UP列表（mid|昵称|签名|最近投稿 相对时间:标题[分区]，最多10条，越靠前越新）：",
    ]
    for up in ups:
        sign = (up.sign or "").replace("|", "／")[:60]
        videos = ";".join(video_data.get(up.mid, {}).get("lines") or []) or "无投稿记录"
        uname = (up.uname or "").replace("|", "／")
        lines.append(f"{up.mid}|{uname}|{sign}|{videos}")
    lines.append("请输出JSON数组。")
    return "\n".join(lines)


def _clean_tags(raw: Any) -> list[str]:
    """Strip, dedupe, cap at 5 tags of at most 16 chars each."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        name = str(item or "").strip()[:16]
        if name and name not in out:
            out.append(name)
        if len(out) >= 5:
            break
    return out


def _normalize_keys(raw: dict[str, Any]) -> dict[str, Any]:
    """Compact keys (m/g/t/c/r) normalize onto the canonical names."""
    item: dict[str, Any] = dict(raw)
    if "m" in item and "mid" not in item:
        item["mid"] = item["m"]
    if "g" in item and "group" not in item:
        item["group"] = item["g"]
    if "t" in item and "tags" not in item:
        item["tags"] = item["t"]
    if "c" in item and "confidence" not in item:
        item["confidence"] = item["c"]
    if "r" in item and "rationale" not in item:
        item["rationale"] = item["r"]
    return item


def _parse_items(content: str) -> list[dict[str, Any]]:
    text = content.strip()
    if text.startswith("```"):
        text = text[3:]
        if text.lower().startswith("json"):
            text = text[4:]
        close = text.rfind("```")
        if close != -1:
            text = text[:close]
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end <= start:
        raise ValueError("response does not contain a JSON array")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, list):
        raise ValueError("response is not a JSON array")
    # Models occasionally ignore the flat format and answer
    # [{"group": "...", "ups": [{"mid": ...}, ...]}]; flatten so the run still
    # counts, then normalize keys on every item (nested ones included).
    flat: list[dict[str, Any]] = []
    for raw in parsed:
        if not isinstance(raw, dict):
            continue
        ups = raw.get("ups")
        if isinstance(ups, list) and raw.get("group"):
            flat.extend(_normalize_keys({**up, "group": raw["group"]}) for up in ups if isinstance(up, dict))
        else:
            flat.append(_normalize_keys(raw))
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


def _ups_in_order(db: Session, mids: list[int]) -> list[UpUser]:
    found = {up.mid: up for up in db.query(UpUser).filter(UpUser.mid.in_(mids)).all()}
    return [found[mid] for mid in mids if mid in found]


def classify_batch(
    db: Session,
    mids: list[int],
    instruction: str = "",
    auto_apply: bool = False,
    threshold: float = 0.9,
) -> dict:
    """Classify one batch of UPs; shared by /review/run and the job runner.

    Counter contract: classified = auto_applied + needs_review; unclassifiable
    and failed complete the partition of the batch.
    """
    result: dict[str, Any] = {
        "classified": 0,
        "auto_applied": 0,
        "needs_review": 0,
        "unclassifiable": 0,
        "failed": 0,
        "created_groups": [],
    }
    cfg = _ai_config(db)
    ups = _ups_in_order(db, mids)
    by_mid = {up.mid: up for up in ups}
    if len(by_mid) < len(mids):
        result["failed"] += len(mids) - len(ups)
    if not ups:
        return result

    previous = _previous_group_names(db, ups)
    fetched = _fetch_missing_archives(db, [up.mid for up in ups])
    now = datetime.now()
    video_data = _video_data(db, [up.mid for up in ups], now)
    group_names = [g.name for g in db.query(GroupLocal).order_by(GroupLocal.sort_order).all()]
    prompt = _build_prompt(ups, group_names, video_data)
    if instruction:
        # appended at the END so the cached prefix (system + group list + UP
        # rows) stays byte-stable across batches with different instructions
        prompt += "\n补充要求：" + instruction.strip()[:300]
    provider = urlparse(str(cfg["base_url"])).netloc
    evidence = {
        mid: {
            "video_count": video_data.get(mid, {}).get("count", 0),
            "source": "fetched" if mid in fetched else "db_cache",
            "sample_titles": video_data.get(mid, {}).get("samples", []),
        }
        for mid in video_data
    }

    try:
        content = _chat(cfg["base_url"], cfg["api_key"], cfg["model"], prompt)
        items = _parse_items(content)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        for up in ups:
            up.ai_status = "error"
        db.commit()
        log.warning("ai classification failed: %s", exc)
        raise ApiError(502, "ai_failed", f"AI 调用或解析失败：{exc}") from exc

    review_threshold = _float_cfg(cfg, "review_threshold", 0.65)
    allow_new = bool(cfg.get("allow_new_categories"))
    seen: set[int] = set()
    for item in items:
        try:
            mid = int(item.get("mid"))
        except (TypeError, ValueError):
            continue
        up = by_mid.get(mid)
        if up is None or mid in seen:
            continue
        seen.add(mid)
        tags = _clean_tags(item.get("tags"))
        try:
            confidence = max(0.0, min(1.0, float(item.get("confidence", 0))))
        except (TypeError, ValueError):
            confidence = 0.0
        name = str(item.get("group") or "").strip()[:64]
        # re-classification and post-pause batch re-runs must replace, not
        # stack: drop the previous open suggestion for this UP (decided
        # accepted/rejected history is kept)
        db.query(AiSuggestion).filter(
            AiSuggestion.up_mid == mid,
            AiSuggestion.status.in_(("pending", "unclassifiable")),
        ).delete(synchronize_session=False)
        suggestion = AiSuggestion(
            up_mid=mid,
            suggested_tags=json.dumps(tags, ensure_ascii=False),
            previous_group_name=previous.get(mid),
            evidence=json.dumps(evidence.get(mid, {}), ensure_ascii=False),
            confidence=confidence,
            rationale=str(item.get("rationale") or "")[:500],
            model=str(cfg["model"]),
            provider=provider,
            prompt_version=PROMPT_VERSION,
        )
        db.add(suggestion)
        if not name or name == _UNCLASSIFIABLE:
            suggestion.suggested_group_name = ""
            suggestion.status = "unclassifiable"
            up.ai_status = "done"
            taxonomy.set_status_labels(db, mid, ["待整理"], source="ai")
            result["unclassifiable"] += 1
            continue
        group, created = taxonomy.ensure_group(db, name, allow_create=allow_new)
        if group is None:
            # creation disabled and nothing matches: keep the raw name so a
            # human can decide (suggested_group_id stays empty)
            suggestion.suggested_group_name = name
            suggestion.status = "pending"
            up.ai_status = "pending"
            result["needs_review"] += 1
            result["classified"] += 1
            continue
        suggestion.suggested_group_name = group.name
        suggestion.suggested_group_id = group.id
        if created:
            result["created_groups"].append(group.name)
        if confidence < review_threshold:
            suggestion.status = "unclassifiable"
            up.ai_status = "done"
            taxonomy.set_status_labels(db, mid, ["待整理"], source="ai")
            result["unclassifiable"] += 1
        elif auto_apply and confidence >= threshold:
            up.group_id = group.id  # primary
            memberships.add_membership(db, up, group.id)
            if tags:
                taxonomy.set_up_tags(db, mid, tags, source="ai")
            taxonomy.clear_status_labels(db, mid, ["待整理", "无法确定"])
            up.ai_status = "done"
            suggestion.status = "accepted"
            suggestion.decided_at = utcnow()
            result["auto_applied"] += 1
            result["classified"] += 1
        else:
            suggestion.status = "pending"
            up.ai_status = "pending"
            result["needs_review"] += 1
            result["classified"] += 1
    for up in ups:
        if up.mid not in seen:
            up.ai_status = "error"  # the model never answered for this UP
            result["failed"] += 1
    db.commit()
    return result


def run_classification(db: Session, batch_size: int = 20, instruction: str = "") -> dict:
    """Compat entry for a single manual batch; suggestions always go to
    review (never auto-applied)."""
    mids = pick_up_mids(db, batch_size)
    if not mids:
        return {
            "classified": 0,
            "auto_applied": 0,
            "needs_review": 0,
            "unclassifiable": 0,
            "failed": 0,
            "created_groups": [],
        }
    return classify_batch(db, mids, instruction=instruction, auto_apply=False)


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
