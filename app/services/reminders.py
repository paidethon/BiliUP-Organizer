"""Reminder rule engine: evaluate rules, dedupe by dedup_key, auto-resolve.

All timestamps are "YYYY-MM-DD HH:MM:SS" UTC strings (see app.util.utcnow);
threshold comparisons are plain string comparisons, which are chronologically
correct for that fixed-width format.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import AiSuggestion, BilibiliAccount, GroupLocal, Reminder, SyncRun, UpUser
from app.services.settings_store import get_section_raw
from app.util import utcnow

log = logging.getLogger(__name__)

RULE_KEYS = (
    "stale_uploader",
    "long_unwatched",
    "never_watched",
    "important_unwatched",
    "low_confidence",
    "login_expired",
    "sync_failed",
    "risk_control",
    "lumirss_failure",
    "ai_failed",
)

# Rules that create reminders scoped to a single UP (dedup_key "{rule}:{mid}").
UP_RULES = ("stale_uploader", "long_unwatched", "never_watched", "important_unwatched", "low_confidence")
# Rules whose open reminder is auto-resolved once the condition clears. lumirss_failure
# is owned by the lumirss service and is never touched here beyond re-opening it.
RESOLVABLE_RULES = frozenset(UP_RULES) | {"login_expired", "risk_control", "sync_failed", "ai_failed"}

_LUMIRSS_KEY = "lumirss_failure:system"

# type ignore: hint payload is (severity, title, body, entity_type, entity_id)
_EXPECTED = dict[str, tuple[str, str, str, str | None, str | None]]


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _cutoff(days: int, now: datetime) -> str:
    return _fmt(now - timedelta(days=days))


def _prefs(db: Session) -> dict:
    raw = get_section_raw(db, "reminders")
    legacy_days = int(raw.get("long_unwatched_days") or 14)
    windows_raw = raw.get("unwatched_days")
    windows: list[int] = []
    if isinstance(windows_raw, list):
        for value in windows_raw:
            try:
                days = int(value)
            except (TypeError, ValueError):
                continue
            if 1 <= days <= 365 and days not in windows:
                windows.append(days)
    if not windows:
        windows = [legacy_days]
    windows = sorted(windows)[:4]
    return {
        "stale_days": int(raw.get("stale_days") or 30),
        "long_unwatched_days": legacy_days,
        "unwatched_days": windows,
        "never_watched_days": int(raw.get("never_watched_days") or 30),
        "low_confidence_threshold": float(raw.get("low_confidence_threshold") or 0.6),
        "weekly_report_enabled": bool(raw.get("weekly_report_enabled", True)),
        "frequency_hours": max(1, int(raw.get("frequency_hours") or 24)),
    }


def _scope_mids(db: Session, raw: dict) -> set[int] | None:
    """UP-scoped rules only fire for these mids; None means every UP."""
    mode = str(raw.get("scope_mode") or "all")
    if mode == "groups":
        ids = {int(g) for g in raw.get("scope_group_ids") or [] if str(g).lstrip("-").isdigit()}
        if not ids:
            return set()
        return {up.mid for up in db.query(UpUser).filter(UpUser.group_id.in_(ids)).all()}
    if mode == "ups":
        return {int(m) for m in raw.get("scope_mids") or [] if str(m).lstrip("-").isdigit()}
    return None


def _up_alerts(
    up: UpUser,
    p: dict,
    now: datetime,
    cutoffs: dict[str, str],
    important_groups: set[int],
    pending: dict[int, AiSuggestion],
) -> _EXPECTED:
    """Expected reminder rows for one active (not skipped) UP."""
    alerts: _EXPECTED = {}
    if up.last_video_at is None or up.last_video_at < cutoffs["stale"]:
        alerts[f"stale_uploader:{up.mid}"] = (
            "info",
            f"UP「{up.uname}」长期未更新",
            f"最近投稿：{up.last_video_at or '无投稿记录'}，已超过 {p['stale_days']} 天。",
            "up_user",
            str(up.mid),
        )
    for days in p["unwatched_days"]:
        cutoff = _cutoff(days, now)
        if up.last_watched_at is not None and up.last_watched_at < cutoff:
            alerts[f"long_unwatched:{up.mid}:{days}"] = (
                "warning",
                f"UP「{up.uname}」{days} 天未观看",
                f"上次观看：{up.last_watched_at}，已超过 {days} 天。",
                "up_user",
                str(up.mid),
            )
    if up.followed_at is not None and up.followed_at < cutoffs["never"] and (up.watched_count or 0) == 0:
        alerts[f"never_watched:{up.mid}"] = (
            "warning",
            f"UP「{up.uname}」关注后从未观看",
            f"关注于 {up.followed_at}，累计观看 0 次，已超过 {p['never_watched_days']} 天。",
            "up_user",
            str(up.mid),
        )
    if (
        up.group_id is not None
        and up.group_id in important_groups
        and up.last_video_at is not None
        and (up.last_watched_at is None or up.last_video_at > up.last_watched_at)
    ):
        watched = up.last_watched_at or "从未观看"
        alerts[f"important_unwatched:{up.mid}"] = (
            "warning",
            f"重要UP「{up.uname}」有新视频未观看",
            f"最新视频「{up.last_video_title or '无标题'}」（{up.last_video_at}），晚于上次观看：{watched}。",
            "up_user",
            str(up.mid),
        )
    suggestion = pending.get(up.mid)
    if suggestion is not None and suggestion.confidence < p["low_confidence_threshold"]:
        alerts[f"low_confidence:{up.mid}"] = (
            "info",
            f"UP「{up.uname}」AI 分类置信度偏低",
            f"建议分组「{suggestion.suggested_group_name}」置信度 {suggestion.confidence:.2f}，"
            f"低于阈值 {p['low_confidence_threshold']}。",
            "up_user",
            str(up.mid),
        )
    return alerts


def _expected_alerts(db: Session, p: dict, now: datetime) -> _EXPECTED:
    """Build the full dedup_key -> payload map implied by current state."""
    cutoffs = {
        "stale": _cutoff(p["stale_days"], now),
        "never": _cutoff(p["never_watched_days"], now),
    }
    important_groups = {g.id for g in db.query(GroupLocal).filter(GroupLocal.is_important.is_(True)).all()}
    pending: dict[int, AiSuggestion] = {}
    rows = (
        db.query(AiSuggestion)
        .filter(AiSuggestion.status == "pending")
        .order_by(AiSuggestion.created_at.asc(), AiSuggestion.id.asc())
        .all()
    )
    for row in rows:
        pending[row.up_mid] = row  # later rows (newer) win

    scope = _scope_mids(db, get_section_raw(db, "reminders"))
    alerts: _EXPECTED = {}
    for up in db.query(UpUser).all():
        if up.missing or up.blacklisted:
            continue
        if up.snoozed_until is not None and up.snoozed_until > _fmt(now):
            continue
        if scope is not None and up.mid not in scope:
            continue
        alerts.update(_up_alerts(up, p, now, cutoffs, important_groups, pending))

    account = db.query(BilibiliAccount).first()
    if account is not None:
        if account.login_status == "expired":
            alerts["login_expired:system"] = (
                "critical",
                "B站登录已过期",
                "Cookie 已失效，请到「账号设置」重新扫码登录。",
                "system",
                "bilibili",
            )
        if account.risk_flag:
            alerts["risk_control:system"] = (
                "critical",
                "B站账号风控告警",
                "检测到风控标记，请降低同步频率或稍后再试。",
                "system",
                "bilibili",
            )
    last_sync = (
        db.query(SyncRun)
        .filter(SyncRun.kind == "followings")
        .order_by(SyncRun.started_at.desc(), SyncRun.id.desc())
        .first()
    )
    if last_sync is not None and last_sync.status == "failed":
        alerts["sync_failed:system"] = (
            "warning",
            "关注列表同步失败",
            f"最近一次同步（{last_sync.started_at}）失败：{last_sync.error or '未知错误'}。",
            "system",
            "sync",
        )
    errored = db.query(UpUser).filter(UpUser.ai_status == "error").first()
    if errored is not None:
        alerts["ai_failed:system"] = (
            "warning",
            "存在 AI 分类失败的 UP",
            f"例如 UP「{errored.uname}」的 ai_status 为 error，请在复核页重试分类。",
            "system",
            "ai",
        )
    return alerts


def run_scan(db: Session) -> dict:
    """Evaluate every rule with thresholds from settings section 'reminders':

    - stale_uploader: last_video_at older than stale_days (NULL counts as stale;
      per-up, not snoozed, not blacklisted, not missing) -> info
    - long_unwatched: for EACH configured window (unwatched_days, e.g. 7/14/30):
      last_watched_at older than that window -> warning (dedup key carries the
      window, so one UP can have several escalation levels open at once)
    - scope_mode 'groups'/'ups' limits UP-scoped rules to the selected groups
      or UPs; 'all' (default) covers everyone
    - never_watched: followed_at older than never_watched_days AND watched_count==0
      -> warning
    - important_unwatched: UP in an is_important group with a video newer than
      last_watched_at (never watched counts) -> warning
    - low_confidence: latest pending ai_suggestion with confidence < threshold -> info
    - login_expired / risk_control / sync_failed / ai_failed: derived from
      bilibili_account, sync_runs and up_users state.
    - lumirss_failure: owned by the lumirss service; never created/resolved here.
      If a row with dedup_key 'lumirss_failure:system' exists and is not open it is
      set back to open.

    Dedup via dedup_key ("{rule}:{mid}" for UP rules, "{rule}:system" otherwise):
    create with status='open' when missing; a 'resolved' row whose condition holds
    again is re-opened (dedup_key is unique); 'acknowledged' rows are left alone.
    When a condition clears, matching open reminders become status='resolved'.
    Snoozed/blacklisted/missing UPs are skipped entirely (their reminders are left
    untouched rather than resolved). Never raises; returns {"created", "resolved"}.
    """
    created = 0
    resolved = 0
    try:
        prefs = _prefs(db)
        now = datetime.now(UTC)
        expected = _expected_alerts(db, prefs, now)
        now_str = utcnow()

        existing: dict[str, Reminder] = {r.dedup_key: r for r in db.query(Reminder).all()}

        for key, (severity, title, body, entity_type, entity_id) in expected.items():
            row = existing.get(key)
            if row is None:
                db.add(
                    Reminder(
                        rule_key=key.split(":", 1)[0],
                        severity=severity,
                        title=title,
                        body=body,
                        entity_type=entity_type,
                        entity_id=entity_id,
                        dedup_key=key,
                        status="open",
                    )
                )
                created += 1
            elif row.status == "resolved":
                row.status = "open"
                row.severity = severity
                row.title = title
                row.body = body
                row.updated_at = now_str
                created += 1

        for key, row in existing.items():
            rule_key = key.split(":", 1)[0]
            if rule_key not in RESOLVABLE_RULES or key in expected:
                continue
            if row.status == "open":
                row.status = "resolved"
                row.updated_at = now_str
                resolved += 1

        lumirss_row = existing.get(_LUMIRSS_KEY)
        if lumirss_row is not None and lumirss_row.status != "open":
            lumirss_row.status = "open"
            lumirss_row.updated_at = now_str

        db.commit()
    except Exception:  # noqa: BLE001 - a scan must never break the scheduler/API
        log.exception("reminder scan failed")
        db.rollback()
    return {"created": created, "resolved": resolved}


def acknowledge(db: Session, reminder_id: int) -> bool:
    """Mark a reminder acknowledged; returns False when it does not exist."""
    row = db.get(Reminder, reminder_id)
    if row is None:
        return False
    row.status = "acknowledged"
    row.updated_at = utcnow()
    db.commit()
    return True
