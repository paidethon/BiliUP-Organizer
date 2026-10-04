# API contract

Base path: `/api/v1`. JSON only. Errors use `{"error": {"code": str, "message": str, "details": any}}`
with an appropriate HTTP status. Authenticated routes require the `biliup_session` cookie;
mutating requests require header `X-CSRF-Token` equal to the `biliup_csrf` cookie.

Public (no auth): `GET /healthz`, `GET /readyz`, `GET /feed/{token}.xml`.

## Auth

| Method | Path | Body | Notes |
| --- | --- | --- | --- |
| GET | /auth/status | – | `{needs_setup, demo_mode, authenticated}` |
| POST | /auth/setup | `{username,password}` | only when no admin exists |
| POST | /auth/login | `{username,password}` | demo mode accepts any credentials |
| POST | /auth/logout | – | |
| GET | /auth/me | – | `{username, demo_mode}` |
| POST | /auth/change-password | `{old_password,new_password}` | |

## Bilibili account & sync

| Method | Path | Notes |
| --- | --- | --- |
| GET | /bilibili/account | `{login_status, mid, uname, avatar, cookie_updated_at, risk_flag, cookie_masked}` |
| POST | /bilibili/qr/start | → `{qrcode_key, qr_url, expires_at}` |
| GET | /bilibili/qr/poll?qrcode_key= | → `{status: waiting\|scanned\|confirmed\|expired, account?}` |
| POST | /bilibili/cookie | `{cookie}` raw header string; parsed server-side |
| POST | /bilibili/logout | clear stored cookie |
| POST | /sync/run | `{kind: followings\|watch_history\|full\|native_groups\|native_overwrite\|native_incremental}` → run record (async). `full` never writes native tags; `native_incremental` is gated by setting `sync.native_push_enabled` |
| GET | /sync/runs?limit= | recent sync runs (default 20, ≤100) |
| GET | /bilibili/native-groups | Bilibili follow tags + local mapping |
| POST | /bilibili/native-groups/sync | refresh tag list from Bilibili (read-only) |
| POST | /bilibili/native-groups/push?dry_run= | `{tag_id, mids[]}`; `dry_run=true` returns the plan without writing |
| POST | /bilibili/native-groups/push-overwrite | `{dry_run: bool}`; dry run previews (would_create/would_delete/would_move/skipped/conflicts), real run backs up → wipes → rebuilds native tags from local groups |

Local categories are unlimited and fully independent of Bilibili's ~20 native
tags; the mapping only materializes during an explicit push.

## Followings, groups & tags

| Method | Path | Notes |
| --- | --- | --- |
| GET | /followings | query: `q, group_id ("none" for ungrouped), flag (stale\|unwatched\|never\|missing\|important), status (explicit status label), tag_id, sort (name\|followed\|last_video\|last_watched), order, page, page_size, all` → `{items, total, page, page_size}`. `all=true` returns the whole filtered result (page=1, page_size=total); otherwise server-paged (page_size ≤ 200). Items include `groups[]`, `tags[]`, `status_labels[]` |
| GET | /followings/{mid} | detail: up (incl. tags/status labels) + recent videos + suggestions + reminders |
| POST | /followings/bulk | `{mids?[], query?, exclude_mids?[], action, params}` → `{ok, changed, undo_id}`. `mids` (≤10000) XOR `query` (same filters as GET /followings) + `exclude_mids`. Actions: `set_group{group_id}, add_to_group{group_id}, remove_from_group{group_id}, clear_group, mark_watched, snooze{days}, unsnooze, blacklist{value}, restore, add_tags{tags:[names]}, remove_tags{tags}, set_status{labels}, clear_status{labels?}, native_move{tag_id}, unfollow{confirm:true}`. Local actions return an `undo_id`; remote/destructive ones (`native_move`, `unfollow`) do not |
| GET | /followings/undo | recent undoable bulk operations `{items: [{id, action, summary, status, item_count, created_at, expires_at}]}` |
| POST | /followings/undo/{id} | revert one bulk operation → `{ok, restored}` |
| GET | /followings/statuses | explicit status labels with UP counts |
| GET | /groups | list with `up_count` and `aliases[]` |
| POST | /groups | `{name,color?,sort_order?,is_important?,description?}` — no quantity cap |
| PATCH | /groups/{id} | partial update |
| DELETE | /groups/{id} | members become ungrouped |
| POST | /groups/{id}/merge | `{into_id}` fold into target (members, aliases, native mapping); undoable |
| GET | /groups/similar | near-duplicate category name clusters `{clusters:[{ids,names}]}` |
| POST | /groups/{id}/aliases | `{alias}` register an alternative name (manual source) |
| DELETE | /groups/{id}/aliases/{alias} | remove an alias |
| GET | /tags | content tags `{id,name,color,up_count}` |
| POST | /tags | `{name,color?}` |
| PATCH | /tags/{id} | `{name?,color?}` |
| DELETE | /tags/{id} | detaches the tag from all UPs |

Classification model: **primary category** = local group (one canonical
dimension, user-managed), **tags** = free-form content labels (many per UP),
**status labels** = explicit states (`新关注 活跃 断更 长期未看 从未观看 重点关注
待整理 低置信度 无法确定 已取关 吃灰`). Derived states (断更/从未观看/已取关…) are
computed from sync data and filtered via `flag`, not stored.

## AI review & classification jobs

| Method | Path | Notes |
| --- | --- | --- |
| GET | /review/queue?status=&page=&page_size=&min_confidence=&max_confidence=&changed_only= | → `{items,total,page,page_size}`; `status ∈ pending\|accepted\|rejected\|unclassifiable\|all`. Items carry `suggested_group_name/id`, `suggested_tags[]`, `previous_group_name`, `confidence`, `rationale`, `evidence`, `model/provider/prompt_version`, `current_group_name`, `recent_videos[]`, `status_labels[]` |
| POST | /review/decide | `{ids:[], decision: accept\|reject\|unclassifiable}`; accept applies category+tags (creates a missing category after explicit user confirmation) |
| POST | /review/run | `{batch_size?, instruction?, auto_apply?, threshold?}` single batch (legacy entry point) |
| GET | /review/status | `{configured, model, pending_count, unclassifiable_count, last_run}` |
| POST | /review/jobs | `{kind: pending\|full, batch_size?, auto_apply?, threshold?}` → create + start the persistent full-library job (400 `classification_job_active` if one is already running/paused). `pending` = only unclassified/errored UPs; `full` = every UP |
| GET | /review/jobs/current | latest job or null |
| GET | /review/jobs | recent jobs |
| POST | /review/jobs/{id}/pause | pauses between batches |
| POST | /review/jobs/{id}/resume | continues (also after a restart — interrupted jobs are marked paused on startup) |
| POST | /review/jobs/{id}/cancel | cancels |
| POST | /review/jobs/{id}/retry-failures | re-queues failed UPs |

Job record: `{id, kind, status: running\|paused\|completed\|cancelled\|failed,
batch_size, auto_apply, threshold, total, processed, classified, auto_applied,
needs_review, unclassifiable, failed, error, created_at, finished_at}`.
Completion requires `processed == total` with no pending cursor; failed items
stay retryable. AI results below `ai.review_threshold` are marked
unclassifiable instead of guessed; `≥ ai.auto_apply_threshold` may be applied
directly when `ai.auto_apply_enabled` is on.

## Reminders

| Method | Path | Notes |
| --- | --- | --- |
| GET | /reminders?status=open\|acknowledged\|resolved\|all | |
| POST | /reminders/{id}/ack | |
| POST | /reminders/ack-all | |
| POST | /reminders/scan | manual rule evaluation → `{created,resolved}` |

## Watch history & weekly report

All statistics use Asia/Shanghai wall clock, Monday-first natural weeks with
half-open ranges, and `metrics_version`-stamped payloads from the shared
stats service (`app/services/stats.py`). Watch duration is progress-derived
estimation: `samples = {valid, bound, unknown}` separates usable / lower-
bound / unusable records; averages divide by valid samples only.

| Method | Path | Notes |
| --- | --- | --- |
| GET | /history/summary?start&end&group_id&up_mid | totals, daily counts, top watched (profile-resolved names), coverage |
| GET | /history?page&q&up_mid&group_id&start&end&hour | filtered history, server-side pagination; `view_at_shanghai` carries an explicit +08:00 offset |
| GET | /weekly-report | latest stored report (legacy compat) |
| GET | /weekly-report/week?date= | Shanghai week metadata for the week containing date + stored revisions |
| GET | /weekly-report/archives | per-week archive summary (latest revision each) |
| GET | /weekly-report/stats?start&end | live aggregation for a half-open Shanghai range |
| POST | /weekly-report/generate | `{week_start, save}` → preview or persisted revision (no SMTP/AI needed) |
| GET | /weekly-report/{id} | one archived revision (frozen snapshot) |
| POST | /weekly-report/{id}/regenerate | explicit new revision; the old one stays readable |
| POST | /weekly-report/{id}/send | email THIS revision's stored snapshot |
| POST | /weekly-report/{id}/ai | optional AI narration of the snapshot (never edits stats) |
| GET | /weekly-report/{id}/export?format=html\|md\|json | offline-readable download |
| POST | /weekly-report/preview | legacy rolling preview (current week) |
| POST | /weekly-report/send | legacy: generate last complete week + email |

## Bilibili native groups (multi-group safe)

| Method | Path | Notes |
| --- | --- | --- |
| GET | /bilibili/native-groups | cached tag map |
| POST | /bilibili/native-groups/sync | refresh tag list from upstream |
| POST | /bilibili/native-groups/push?dry_run= | add members to one tag |
| POST | /bilibili/native-groups/push-plan | `{mode: append\|replace}` read-only convergence preview (R ∪ D / (R − M) ∪ D) |
| POST | /bilibili/native-groups/push-run | start tracked background push; progress via /bilibili/sync/runs |
| POST | /bilibili/native-groups/push-overwrite | `{dry_run}` managed-scope rebuild (backup-first; unmapped remote tags preserved) |

Upstream Bilibili failures map to structured 502 errors
(`bili_auth` / `bili_csrf` / `bili_risk_control` / `bili_http` / `bili_contract` /
`bili_param`) instead of opaque 500s. Group writes submit each UP's FULL
target relation set (addUsers is set-replacement upstream); unmanaged groups
and 特别关注 are always preserved; every write is read back and verified.

## Settings (secrets masked; empty secret value on PUT = keep existing)

Sections: `ai, smtp, lumirss, reminders, sync`.
`GET /settings` → all sections. `PUT /settings/{section}` body = section object.
`POST /settings/test/{what}` with `what ∈ {email, ai, lumirss}` → `{ok, message}`.
`POST /settings/lumirss/detect` probes candidate LumiRSS URLs and saves a hit.

`ai` extras: `grouping_instructions`, `auto_apply_enabled`,
`auto_apply_threshold` (default 0.9), `review_threshold` (default 0.65),
`allow_new_categories` (default false). `sync` extras: `native_push_enabled`
(default false).

## Feeds

Auth: `GET /feeds`, `POST /feeds {name, group_id?, max_items?}`, `DELETE /feeds/{id}`.
Public: `GET /feed/{token}.xml` (Atom; also `/feed/{token}`).

## System

| Method | Path | Notes |
| --- | --- | --- |
| GET | /system/stats | dashboard counts |
| GET | /system/audit?page=&page_size= | audit log |
| GET | /system/backups | list |
| POST | /system/backups | create now |
| GET | /system/backups/{id}/download | file download |
| POST | /system/backups/restore | multipart `file` upload; restores SQLite |
| GET | /system/info | `{version, app_env, demo_mode, scheduler_enabled}` |
