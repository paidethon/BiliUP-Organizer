from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Explicit status labels (stored in up_status_labels). Derived states such as
# 断更/长期未看/从未观看/已取关 are computed from up_users fields and filtered
# via the existing `flag` parameter — they are not stored per-UP.
STATUS_LABELS = (
    "新关注",
    "活跃",
    "断更",
    "长期未看",
    "从未观看",
    "重点关注",
    "待整理",
    "低置信度",
    "无法确定",
    "已取关",
    "吃灰",
)


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
    groups: list[dict] = []
    tags: list[dict] = []
    status_labels: list[str] = []


class TagOut(OrmModel):
    id: int
    name: str
    color: str
    up_count: int = 0


class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=32)
    color: str = "#64748b"


class TagPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=32)
    color: str | None = None


class GroupOut(OrmModel):
    id: int
    name: str
    color: str
    sort_order: int
    is_important: bool
    description: str
    up_count: int = 0
    aliases: list[str] = []


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


class GroupMergeIn(BaseModel):
    into_id: int


class AliasIn(BaseModel):
    alias: str = Field(min_length=1, max_length=64)


class BulkQuery(BaseModel):
    """Same filters as GET /followings, for whole-result bulk operations."""

    q: str | None = None
    group_id: str | None = None
    flag: str | None = None
    status: str | None = None
    tag_id: str | None = None
    sort: str = "followed"
    order: str = "desc"


class BulkIn(BaseModel):
    mids: list[int] | None = None
    exclude_mids: list[int] = []
    query: BulkQuery | None = None
    action: str
    params: dict = Field(default_factory=dict)


class BulkOut(BaseModel):
    ok: bool
    changed: int
    undo_id: int | None = None


class NativeGroupOut(OrmModel):
    bili_tag_id: int
    bili_tag_name: str
    local_group_id: int | None
    synced_at: str | None


class NativePushIn(BaseModel):
    tag_id: int
    mids: list[int] = Field(min_length=1)


class NativeOverwriteIn(BaseModel):
    dry_run: bool = False


class NativePlanOut(BaseModel):
    mode: str  # overwrite | incremental
    dry_run: bool
    would_create_tags: list[str] = []
    would_delete_tags: list[str] = []
    would_move: int = 0
    skipped: int = 0
    conflicts: list[str] = []
    notes: list[str] = []


class SimilarGroupCluster(BaseModel):
    ids: list[int]
    names: list[str]


class SimilarGroupsOut(BaseModel):
    clusters: list[SimilarGroupCluster]


class SuggestionOut(OrmModel):
    id: int
    up_mid: int
    up_uname: str = ""
    up_face: str = ""
    suggested_group_id: int | None
    suggested_group_name: str
    suggested_tags: list[str] = []
    previous_group_name: str | None = None
    confidence: float
    rationale: str
    evidence: dict = {}
    model: str
    provider: str = ""
    prompt_version: str = ""
    status: str
    created_at: str
    current_group_name: str | None = None
    recent_videos: list[dict] = []
    status_labels: list[str] = []

    @field_validator("suggested_tags", "recent_videos", mode="before")
    @classmethod
    def _parse_json_list(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return []
        return value

    @field_validator("evidence", mode="before")
    @classmethod
    def _parse_json_obj(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return {}
        return value


class ReviewDecideIn(BaseModel):
    ids: list[int] = Field(min_length=1)
    decision: str  # accept | reject | unclassifiable


class ReviewRunIn(BaseModel):
    batch_size: int = 20
    # one-off requirement from the review page; empty -> ai.grouping_instructions
    instruction: str = Field(default="", max_length=800)
    # one-off confidence-workflow overrides; None -> values from ai settings
    auto_apply: bool | None = None
    threshold: float | None = Field(default=None, ge=0.0, le=1.0)


class ClassificationJobCreateIn(BaseModel):
    kind: str  # pending | full
    batch_size: int = Field(default=20, ge=5, le=100)
    auto_apply: bool = False
    threshold: float = Field(default=0.9, ge=0.0, le=1.0)


class ClassificationJobOut(OrmModel):
    id: int
    kind: str
    status: str
    batch_size: int
    auto_apply: bool
    threshold: float
    total: int
    processed: int
    classified: int
    auto_applied: int
    needs_review: int
    unclassifiable: int
    failed: int
    error: str | None
    created_at: str
    finished_at: str | None


class ClassificationJobListOut(BaseModel):
    items: list[ClassificationJobOut]


class UndoRecordOut(OrmModel):
    id: int
    action: str
    summary: str
    status: str
    created_at: str
    expires_at: str
    item_count: int = 0


class ReviewStatusOut(BaseModel):
    configured: bool
    model: str
    pending_count: int
    last_run: str | None = None
    unclassifiable_count: int = 0


class StatusLabelCount(BaseModel):
    label: str
    count: int


class StatusLabelsOut(BaseModel):
    labels: list[StatusLabelCount]


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
    # confidence workflow: >= auto_apply_threshold applies directly (when
    # enabled), review_threshold..auto_apply_threshold goes to human review,
    # below review_threshold is marked 无法确定 instead of guessed
    auto_apply_enabled: bool = False
    auto_apply_threshold: float = Field(default=0.9, ge=0.0, le=1.0)
    review_threshold: float = Field(default=0.65, ge=0.0, le=1.0)
    allow_new_categories: bool = False


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
    # remote bilibili group writes: scheduler push stays off unless opted in
    native_push_enabled: bool = False


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
