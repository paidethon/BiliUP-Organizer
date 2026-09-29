from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Float, Integer, String, Text
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
    created_at: Mapped[str] = mapped_column(Text, default=_ts)


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


class AiSuggestion(Base):
    __tablename__ = "ai_suggestions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    up_mid: Mapped[int] = mapped_column(Integer, index=True)
    suggested_group_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suggested_group_name: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    rationale: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(Text, default="pending", index=True)  # pending|accepted|rejected
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
