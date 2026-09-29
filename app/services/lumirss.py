"""LumiRSS Inbox push adapter (frozen contract from the stub docstring).

Implements the LumiRSS machine endpoint documented in docs/RESEARCH_LUMIRSS.md:
POST {base_url}{inbox_endpoint} with ``Authorization: Bearer <token>`` and a
JSON body of ingest items (guid=bvid is the idempotency key; replays answer
{"status": "exists"}). Owned by the main agent after the RSS subagent hit the
concurrency limit.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.models import LumirssPushLog, Reminder
from app.services.settings_store import get_section_raw
from app.util import utcnow

log = logging.getLogger(__name__)

DEFAULT_INBOX_ENDPOINT = "/api/v1/inbox/ingest/"
_MAX_ATTEMPTS = 3
_BACKOFFS = (0.5, 1.0, 2.0)


def _config(db: Session) -> dict[str, Any]:
    cfg = get_section_raw(db, "lumirss")
    if not cfg.get("enabled") or not cfg.get("base_url") or not cfg.get("token"):
        return {}
    return cfg


def _ingest_url(cfg: dict[str, Any]) -> str:
    endpoint = str(cfg.get("inbox_endpoint") or DEFAULT_INBOX_ENDPOINT)
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    return cfg["base_url"].rstrip("/") + endpoint


def _entry_payload(item: dict[str, Any]) -> dict[str, Any]:
    """Map a collect_entries row to the LumiRSS InboxIngestItem shape."""
    payload: dict[str, Any] = {"guid": str(item["bvid"])}
    if item.get("title"):
        payload["title"] = str(item["title"])[:512]
    if item.get("bvid"):
        payload["url"] = f"https://www.bilibili.com/video/{item['bvid']}"
    if item.get("up_uname"):
        payload["author"] = str(item["up_uname"])[:256]
    if item.get("pubdate"):
        payload["publishedAt"] = str(item["pubdate"]).replace(" ", "T") + "Z"
    if item.get("up_uname"):
        payload["categories"] = [str(item["up_uname"])[:64]]
    return payload


def _ensure_failure_reminder(db: Session, detail: str) -> None:
    existing = db.query(Reminder).filter(Reminder.dedup_key == "lumirss_failure:system").first()
    if existing is not None:
        if existing.status != "open":
            existing.status = "open"
            existing.body = detail[:1000]
            existing.updated_at = utcnow()
            db.commit()
        return
    db.add(
        Reminder(
            rule_key="lumirss_failure",
            severity="warning",
            title="LumiRSS 推送失败",
            body=detail[:1000],
            entity_type="system",
            entity_id="lumirss",
            dedup_key="lumirss_failure:system",
        )
    )
    db.commit()


def push_items(db: Session, items: list[dict[str, Any]]) -> dict:
    """Push entries to LumiRSS with retries; idempotent by guid."""
    cfg = _config(db)
    if not cfg or not items:
        return {"pushed": 0, "failed": 0}
    url = _ingest_url(cfg)
    headers = {"Authorization": f"Bearer {cfg['token']}"}
    pushed = failed = 0
    with httpx.Client(timeout=30.0) as client:
        for item in items:
            payload = _entry_payload(item)
            ok = False
            last_detail = ""
            for attempt in range(_MAX_ATTEMPTS):
                try:
                    resp = client.post(url, json=payload, headers=headers)
                    if resp.status_code in (200, 201, 202):
                        ok = True
                        last_detail = str(resp.json().get("status", "ok"))[:200]
                        break
                    last_detail = f"HTTP {resp.status_code}: {resp.text[:200]}"
                except httpx.HTTPError as exc:
                    last_detail = f"{type(exc).__name__}: {exc}"
                if attempt < _MAX_ATTEMPTS - 1:
                    time.sleep(_BACKOFFS[attempt])
            db.add(
                LumirssPushLog(
                    bvid=payload["guid"],
                    status="success" if ok else "failed",
                    detail=last_detail,
                )
            )
            if ok:
                pushed += 1
            else:
                failed += 1
        db.commit()
    if failed:
        _ensure_failure_reminder(
            db, f"LumiRSS 推送失败 {failed} 条（端点 {_ingest_url(cfg)}），最近错误：{last_detail}"
        )
    return {"pushed": pushed, "failed": failed}


def push_pending(db: Session) -> dict:
    """Push videos newer than the last successful push (or last 7 days)."""
    cfg = _config(db)
    if not cfg:
        return {"pushed": 0, "failed": 0}

    from datetime import datetime, timedelta

    from app.models import UpUser, Video

    last_success = (
        db.query(LumirssPushLog)
        .filter(LumirssPushLog.status == "success")
        .order_by(LumirssPushLog.id.desc())
        .first()
    )
    if last_success is not None and last_success.created_at:
        try:
            since = datetime.strptime(last_success.created_at[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        except ValueError:
            since = datetime.now(UTC) - timedelta(days=7)
    else:
        since = datetime.now(UTC) - timedelta(days=7)
    cutoff = since.strftime("%Y-%m-%d %H:%M:%S")

    rows = (
        db.query(Video, UpUser)
        .join(UpUser, UpUser.mid == Video.up_mid)
        .filter(UpUser.missing.is_(False), UpUser.blacklisted.is_(False), Video.pubdate > cutoff)
        .order_by(Video.pubdate.desc())
        .limit(100)
        .all()
    )
    items = [
        {
            "bvid": video.bvid,
            "title": video.title,
            "pubdate": video.pubdate,
            "up_uname": up.uname,
        }
        for video, up in rows
    ]
    return push_items(db, items)


def test_connection(db: Session) -> tuple[bool, str]:
    cfg = _config(db)
    if not cfg:
        return False, "LumiRSS 未配置或未启用"
    url = _ingest_url(cfg)
    guid = f"test-{utcnow().replace(' ', 'T')}"
    try:
        resp = httpx.post(
            url,
            headers={"Authorization": f"Bearer {cfg['token']}"},
            json={"guid": guid, "title": "[BiliUP Organizer] 连接测试"},
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        return False, f"连接失败：{exc}"
    if resp.status_code in (200, 201, 202):
        status = str(resp.json().get("status", "ok"))
        return True, f"连接成功（{status}）"
    if resp.status_code in (401, 404):
        hint = "检查 token 与 ingest 路径，宿主反代需豁免该路径"
        return False, f"认证或路径错误（HTTP {resp.status_code}）：{hint}"
    return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
