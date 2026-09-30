from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class StatusOut(BaseModel):
    needs_setup: bool
    demo_mode: bool
    authenticated: bool


class MeOut(BaseModel):
    username: str
    demo_mode: bool


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class SetupIn(LoginIn):
    pass


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8, max_length=128)


class BilibiliAccountOut(BaseModel):
    login_status: str
    mid: int | None = None
    uname: str | None = None
    avatar: str | None = None
    cookie_updated_at: str | None = None
    risk_flag: bool = False
    cookie_masked: str = ""


class QrStartOut(BaseModel):
    qrcode_key: str
    qr_url: str
    expires_at: str


class QrPollOut(BaseModel):
    status: str  # waiting | scanned | confirmed | expired
    account: BilibiliAccountOut | None = None


class CookieIn(BaseModel):
    cookie: str = Field(min_length=1, max_length=8192)


class SyncRunOut(OrmModel):
    id: int
    kind: str
    status: str
    started_at: str
    finished_at: str | None = None
    stats: dict | None = None
    error: str | None = None


class SyncRunIn(BaseModel):
    kind: str  # followings | watch_history | full | native_groups


class UpUserOut(OrmModel):
    mid: int
    uname: str
    sign: str
    face: str
    official_type: int
    special: bool
    followed_at: str | None
    group_id: int | None
    last_video_bvid: str | None
    last_video_title: str | None
    last_video_at: str | None
    last_seen_at: str | None
    missing: bool
    last_watched_at: str | None
    watched_count: int
    snoozed_until: str | None
    blacklisted: bool
    ai_status: str


class GroupOut(OrmModel):
    id: int
    name: str
    color: str
    sort_order: int
    is_important: bool
    description: str
    up_count: int = 0


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    color: str = "#6366f1"
    sort_order: int = 0
    is_important: bool = False
    description: str = ""


class GroupPatchIn(BaseModel):
    name: str | None = None
    color: str | None = None
    sort_order: int | None = None
    is_important: bool | None = None
    description: str | None = None


class BulkIn(BaseModel):
    mids: list[int] = Field(min_length=1)
    action: str
    params: dict = Field(default_factory=dict)


class NativeGroupOut(OrmModel):
    bili_tag_id: int
    bili_tag_name: str
    local_group_id: int | None
    synced_at: str | None


class NativePushIn(BaseModel):
    tag_id: int
    mids: list[int] = Field(min_length=1)


class SuggestionOut(OrmModel):
    id: int
    up_mid: int
    up_uname: str = ""
    suggested_group_id: int | None
    suggested_group_name: str
    confidence: float
    rationale: str
    model: str
    status: str
    created_at: str


class ReviewDecideIn(BaseModel):
    ids: list[int] = Field(min_length=1)
    decision: str  # accept | reject


class ReviewRunIn(BaseModel):
    batch_size: int = 20
    # one-off requirement from the review page; empty -> ai.grouping_instructions
    instruction: str = Field(default="", max_length=500)


class ReviewStatusOut(BaseModel):
    configured: bool
    model: str
    pending_count: int
    last_run: str | None = None


class ReminderOut(OrmModel):
    id: int
    rule_key: str
    severity: str
    title: str
    body: str
    entity_type: str | None
    entity_id: str | None
    dedup_key: str
    status: str
    created_at: str


class ReminderScanOut(BaseModel):
    created: int
    resolved: int


class AiSection(BaseModel):
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    enabled: bool = False
    configured: bool = False
    # free-form grouping guidance appended to every classification prompt
    grouping_instructions: str = ""


class SmtpSection(BaseModel):
    host: str = ""
    port: int = 465
    username: str = ""
    password: str = ""
    from_addr: str = ""
    to_addr: str = ""
    use_tls: bool = True
    enabled: bool = False
    configured: bool = False


class LumirssSection(BaseModel):
    base_url: str = ""
    token: str = ""
    inbox_endpoint: str = ""
    enabled: bool = False
    configured: bool = False


class ReminderPrefs(BaseModel):
    stale_days: int = 30
    long_unwatched_days: int = 14
    never_watched_days: int = 30
    low_confidence_threshold: float = 0.6
    email_enabled: bool = False
    weekly_report_enabled: bool = True
    # multi-window "not watched" reminders, ascending days (e.g. 7/14/30)
    unwatched_days: list[int] = [14]
    # limit UP-scoped reminders to specific groups or UPs
    scope_mode: str = "all"  # all | groups | ups
    scope_group_ids: list[int] = []
    scope_mids: list[int] = []
    # how often the reminder engine runs (hours); wired into the scheduler
    frequency_hours: int = 24


class SyncPrefs(BaseModel):
    interval_hours: int = 6
    history_enabled: bool = True
    history_max_pages: int = 5
    history_window_days: int = 14


class SettingsOut(BaseModel):
    ai: AiSection
    smtp: SmtpSection
    lumirss: LumirssSection
    reminders: ReminderPrefs
    sync: SyncPrefs


class TestResultOut(BaseModel):
    ok: bool
    message: str


class FeedOut(OrmModel):
    id: int
    name: str
    token: str
    group_id: int | None
    group_name: str | None = None
    max_items: int
    created_at: str


class FeedIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    group_id: int | None = None
    max_items: int = 50


class HistorySummaryOut(BaseModel):
    total_entries: int
    entries_30d: int
    distinct_ups_watched: int
    top_watched: list[dict]
    daily_counts: list[dict]


class WeeklyReportOut(BaseModel):
    generated_at: str | None = None
    html: str | None = None


class StatsOut(BaseModel):
    total_ups: int
    grouped_ups: int
    ungrouped_ups: int
    missing_ups: int
    groups: int
    open_reminders: int
    pending_suggestions: int
    videos_tracked: int
    last_sync: str | None = None
    login_status: str


class AuditOut(OrmModel):
    id: int
    at: str
    actor: str
    action: str
    entity_type: str | None
    entity_id: str | None
    detail_json: str | None


class BackupOut(OrmModel):
    id: int
    filename: str
    size_bytes: int
    kind: str
    note: str
    created_at: str


class SystemInfoOut(BaseModel):
    version: str
    app_env: str
    demo_mode: bool
    scheduler_enabled: bool
