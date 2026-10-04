from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _ts() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")  # noqa: DTZ003


class AdminUser(Base):
    __tablename__ = "admin_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, default=_ts)


class Session(Base):
    __tablename__ = "sessions"
    token: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[str] = mapped_column(Text, default=_ts)
    expires_at: Mapped[str] = mapped_column(Text)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text)  # JSON encoded
    updated_at: Mapped[str] = mapped_column(Text, default=_ts, onupdate=_ts)


class BilibiliAccount(Base):
    __tablename__ = "bilibili_account"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uname: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar: Mapped[str | None] = mapped_column(Text, nullable=True)
    cookie_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    cookie_updated_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    login_status: Mapped[str] = mapped_column(Text, default="none")  # none|active|expired
    risk_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[str] = mapped_column(Text, default=_ts, onupdate=_ts)


class GroupLocal(Base):
    __tablename__ = "groups_local"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    color: Mapped[str] = mapped_column(Text, default="#6366f1")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_important: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(Text, default="")


class GroupMember(Base):
    """UP ↔ local-group membership (many-to-many).

    up_users.group_id stays as the PRIMARY group (native-tag sync bookkeeping);
    every group an UP appears in — including the primary — lives here.
    """

    __tablename__ = "group_members"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    up_mid: Mapped[int] = mapped_column(Integer, index=True)
    group_id: Mapped[int] = mapped_column(Integer, index=True)
    __table_args__ = (UniqueConstraint("up_mid", "group_id", name="uq_group_members_up_group"),)
    created_at: Mapped[str] = mapped_column(Text, default=_ts)


class Tag(Base):
    """Free-form content tags; one UP can carry many (independent of groups)."""

    __tablename__ = "tags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    color: Mapped[str] = mapped_column(Text, default="#64748b")
    created_at: Mapped[str] = mapped_column(Text, default=_ts)


class UpTag(Base):
    __tablename__ = "up_tags"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    up_mid: Mapped[int] = mapped_column(Integer, index=True)
    tag_id: Mapped[int] = mapped_column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(Text, default="manual")  # manual|ai
    __table_args__ = (UniqueConstraint("up_mid", "tag_id", name="uq_up_tags_up_tag"),)


class UpStatusLabel(Base):
    """Explicit status labels (待整理 / 吃灰 / 重点关注 ...), fully separate from
    content categories. Derived states like 断更/从未观看 stay computed from
    up_users fields and are never stored here."""

    __tablename__ = "up_status_labels"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    up_mid: Mapped[int] = mapped_column(Integer, index=True)
    label: Mapped[str] = mapped_column(Text, index=True)
    source: Mapped[str] = mapped_column(Text, default="manual")  # manual|ai|sync
    created_at: Mapped[str] = mapped_column(Text, default=_ts)
    __table_args__ = (UniqueConstraint("up_mid", "label", name="uq_up_status_up_label"),)


class GroupAlias(Base):
    """Alternative names that resolve to a primary category; keeps the AI
    vocabulary stable (科技/科技区/数码科技 -> 科技数码)."""

    __tablename__ = "group_aliases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("groups_local.id", ondelete="CASCADE"), index=True
    )
    alias: Mapped[str] = mapped_column(Text, unique=True)
    source: Mapped[str] = mapped_column(Text, default="manual")  # manual|auto
    created_at: Mapped[str] = mapped_column(Text, default=_ts)


class ClassificationJob(Base):
    """Persistent full-library classification job; survives restarts."""

    __tablename__ = "classification_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(Text)  # pending | full
    status: Mapped[str] = mapped_column(
        Text, default="running", index=True
    )  # running|paused|completed|cancelled|failed
    batch_size: Mapped[int] = mapped_column(Integer, default=20)
    auto_apply: Mapped[bool] = mapped_column(Boolean, default=False)
    threshold: Mapped[float] = mapped_column(Float, default=0.9)
    total: Mapped[int] = mapped_column(Integer, default=0)
    processed: Mapped[int] = mapped_column(Integer, default=0)
    classified: Mapped[int] = mapped_column(Integer, default=0)
    auto_applied: Mapped[int] = mapped_column(Integer, default=0)
    needs_review: Mapped[int] = mapped_column(Integer, default=0)
    unclassifiable: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    # {"mids": [...], "index": int, "failed": [mid, ...]}
    cursor_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=_ts)
    updated_at: Mapped[str] = mapped_column(Text, default=_ts, onupdate=_ts)
    finished_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class UndoRecord(Base):
    """Revertible bulk-operation log; expiry-based cleanup."""

    __tablename__ = "undo_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[str] = mapped_column(Text)  # enough state to revert exactly
    status: Mapped[str] = mapped_column(Text, default="active", index=True)  # active|undone|expired
    created_at: Mapped[str] = mapped_column(Text, default=_ts)
    expires_at: Mapped[str] = mapped_column(Text)


class UpUser(Base):
    __tablename__ = "up_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mid: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    uname: Mapped[str] = mapped_column(Text)
    sign: Mapped[str] = mapped_column(Text, default="")
    face: Mapped[str] = mapped_column(Text, default="")
    official_type: Mapped[int] = mapped_column(Integer, default=-1)
    special: Mapped[bool] = mapped_column(Boolean, default=False)
    followed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    group_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    native_tag_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_video_bvid: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_video_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_video_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    missing: Mapped[bool] = mapped_column(Boolean, default=False)
    last_watched_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    watched_count: Mapped[int] = mapped_column(Integer, default=0)
    snoozed_until: Mapped[str | None] = mapped_column(Text, nullable=True)
    blacklisted: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_status: Mapped[str] = mapped_column(Text, default="none")  # none|pending|done|error
    created_at: Mapped[str] = mapped_column(Text, default=_ts)
    updated_at: Mapped[str] = mapped_column(Text, default=_ts, onupdate=_ts)


class NativeGroupMap(Base):
    __tablename__ = "native_group_map"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bili_tag_id: Mapped[int] = mapped_column(Integer, unique=True)
    bili_tag_name: Mapped[str] = mapped_column(Text)
    local_group_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    synced_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class Video(Base):
    __tablename__ = "videos"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bvid: Mapped[str] = mapped_column(Text, unique=True)
    up_mid: Mapped[int] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(Text)
    tname: Mapped[str | None] = mapped_column(Text, nullable=True)
    pubdate: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=_ts)


class WatchHistory(Base):
    __tablename__ = "watch_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bvid: Mapped[str] = mapped_column(Text)
    up_mid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(Text, default="")
    view_at: Mapped[str] = mapped_column(Text, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)


class WatchAuthor(Base):
    """Per-record author snapshot captured at history-sync time (one row per
    watch_history id). Preserves the name/face seen when the record was synced
    even if the profile cache later changes; used as the last-resort display
    name for UPs that are neither followed nor freshly cached."""

    __tablename__ = "watch_authors"
    history_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    author_mid: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    author_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_face: Mapped[str | None] = mapped_column(Text, nullable=True)


class UpProfile(Base):
    """Display-name/avatar cache for ANY mid seen in syncs — including UPs the
    account never followed. Sourced from followings sync, history author
    snapshots or bounded userinfo lookups; never a substitute for UpUser."""

    __tablename__ = "up_profiles"
    mid: Mapped[int] = mapped_column(Integer, primary_key=True)
    uname: Mapped[str | None] = mapped_column(Text, nullable=True)
    face: Mapped[str | None] = mapped_column(Text, nullable=True)
    # followings | history | userinfo
    source: Mapped[str] = mapped_column(Text, default="history")
    updated_at: Mapped[str] = mapped_column(Text, default=_ts, onupdate=_ts)
    # negative-cache bookkeeping for the bounded lookup queue
    last_attempt_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class WeeklyReport(Base):
    """Persisted weekly report archive with revisions.

    period_start/period_end_exclusive are Shanghai calendar dates and the
    interval is half-open: [period_start 00:00, period_end_exclusive 00:00).
    stats_json is the frozen snapshot every rendering surface (page, HTML,
    Markdown, JSON export, email, AI) must reuse — nothing recomputes numbers
    from "today" when showing an archived week.
    """

    __tablename__ = "weekly_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(Text, default="default", index=True)
    period_start: Mapped[str | None] = mapped_column(Text, index=True, nullable=True)
    period_end_exclusive: Mapped[str | None] = mapped_column(Text, nullable=True)
    timezone: Mapped[str] = mapped_column(Text, default="Asia/Shanghai")
    metrics_version: Mapped[str] = mapped_column(Text, default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    is_legacy: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(Text, default="archived")  # archived|sent
    generated_at: Mapped[str] = mapped_column(Text, default=_ts)
    # observation cutoff: data after this moment is NOT reflected in stats
    data_cutoff: Mapped[str | None] = mapped_column(Text, nullable=True)
    coverage_json: Mapped[str] = mapped_column(Text, default="{}")
    stats_json: Mapped[str] = mapped_column(Text, default="{}")
    html: Mapped[str] = mapped_column(Text, default="")
    ai_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    send_status: Mapped[str | None] = mapped_column(Text, nullable=True)  # sent|failed
    sent_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_to: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(Text, default="", index=True)
    created_at: Mapped[str] = mapped_column(Text, default=_ts)
    __table_args__ = (
        UniqueConstraint("scope", "period_start", "revision", name="uq_weekly_scope_period_rev"),
    )


class AiSuggestion(Base):
    __tablename__ = "ai_suggestions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    up_mid: Mapped[int] = mapped_column(Integer, index=True)
    suggested_group_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suggested_group_name: Mapped[str] = mapped_column(Text, default="")
    suggested_tags: Mapped[str] = mapped_column(Text, default="[]")  # JSON array of tag names
    previous_group_name: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # category at classification time
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    rationale: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[str] = mapped_column(Text, default="{}")  # JSON: info sources used, no secrets
    model: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(Text, default="")
    prompt_version: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(
        Text, default="pending", index=True
    )  # pending|accepted|rejected|unclassifiable
    created_at: Mapped[str] = mapped_column(Text, default=_ts)
    decided_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class Reminder(Base):
    __tablename__ = "reminders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_key: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text, default="info")  # info|warning|critical
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text, default="")
    entity_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedup_key: Mapped[str] = mapped_column(Text, unique=True)
    status: Mapped[str] = mapped_column(Text, default="open", index=True)  # open|acknowledged|resolved
    notified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[str] = mapped_column(Text, default=_ts)
    updated_at: Mapped[str] = mapped_column(Text, default=_ts, onupdate=_ts)


class SyncRun(Base):
    __tablename__ = "sync_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="running")  # running|success|failed
    started_at: Mapped[str] = mapped_column(Text, default=_ts)
    finished_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    stats_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class FeedToken(Base):
    __tablename__ = "feed_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text)
    token: Mapped[str] = mapped_column(Text, unique=True)
    group_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_items: Mapped[int] = mapped_column(Integer, default=50)
    created_at: Mapped[str] = mapped_column(Text, default=_ts)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[str] = mapped_column(Text, default=_ts, index=True)
    actor: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class Backup(Base):
    __tablename__ = "backups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(Text, default="manual")  # manual|scheduled
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(Text, default=_ts)


class LumirssPushLog(Base):
    __tablename__ = "lumirss_push_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    bvid: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text)  # success|failed
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[str] = mapped_column(Text, default=_ts)
