# API contract (frozen)

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
| POST | /sync/run | `{kind: followings\|watch_history\|full\|native_groups}` → run record |
| GET | /sync/runs?limit= | recent sync runs |
| GET | /bilibili/native-groups | Bilibili follow tags + local mapping |
| POST | /bilibili/native-groups/sync | refresh tag list from Bilibili |
| POST | /bilibili/native-groups/push | `{tag_id, mids[]}` add users to a native tag |

## Followings & groups

| Method | Path | Notes |
| --- | --- | --- |
| GET | /followings | query: `q, group_id ("none" for ungrouped), flag (stale\|unwatched\|never\|missing\|important), sort (name\|followed\|last_video\|last_watched), order, page, page_size` → `{items,total}` |
| GET | /followings/{mid} | detail: up + recent videos + suggestions + reminders |
| POST | /followings/bulk | `{mids:[], action, params}` actions: `set_group, clear_group, mark_watched, snooze, unsnooze, blacklist, restore, native_move, unfollow` |
| GET | /groups | list with `up_count` |
| POST | /groups | `{name,color?,sort_order?,is_important?,description?}` |
| PATCH | /groups/{id} | partial update |
| DELETE | /groups/{id} | members become ungrouped |

## AI review

| Method | Path | Notes |
| --- | --- | --- |
| GET | /review/queue?status=&page= | ai_suggestions joined with up_users |
| POST | /review/decide | `{ids:[], decision: accept\|reject}` accept assigns group |
| POST | /review/run | `{batch_size?}` → classification stats |
| GET | /review/status | `{configured, model, pending_count, last_run}` |

## Reminders

| Method | Path | Notes |
| --- | --- | --- |
| GET | /reminders?status=open\|acknowledged\|all | |
| POST | /reminders/{id}/ack | |
| POST | /reminders/ack-all | |
| POST | /reminders/scan | manual rule evaluation → `{created,resolved}` |

## Watch history & weekly report

| Method | Path | Notes |
| --- | --- | --- |
| GET | /history/summary | totals, 30-day daily counts, top watched, backlog |
| GET | /history?page= | recent history entries |
| GET | /weekly-report | latest generated report metadata (+ html) |
| POST | /weekly-report/preview | returns generated html now |
| POST | /weekly-report/send | build + email now |

## Settings (secrets masked; empty secret value on PUT = keep existing)

Sections: `ai, smtp, lumirss, reminders, sync, general`.
`GET /settings` → all sections. `PUT /settings/{section}` body = section object.
`POST /settings/test/{what}` with `what ∈ {email, ai, lumirss}` → `{ok, message}`.

## Feeds

Auth: `GET /feeds`, `POST /feeds {name, group_id?, max_items?}`, `DELETE /feeds/{id}`.
Public: `GET /feed/{token}.xml` (Atom; also `/feed/{token}`).

## System

| Method | Path | Notes |
| --- | --- | --- |
| GET | /system/stats | dashboard counts |
| GET | /system/audit?page= | audit log |
| GET | /system/backups | list |
| POST | /system/backups | create now |
| GET | /system/backups/{id}/download | file download |
| POST | /system/backups/restore | multipart `file` upload; restores SQLite |
| GET | /system/info | `{version, env, python, scheduler}` |
