# Architecture (frozen contract)

Last updated: 2026-09-29. The database schema and the `/api/v1` contract described
here are the coordination point between all implementation agents. Changing them
requires updating this file in the same commit.

## Stack

- Backend: Python 3.11+, FastAPI, SQLAlchemy 2 (sync), SQLite (WAL), APScheduler.
- Frontend: React 18 + TypeScript + Vite + Tailwind v4 + TanStack Query + react-router.
- Deployment: single versioned Docker image (GHCR), Caddy reverse proxy, `/data` volume for SQLite + backups.
- Everything runs locally in WSL for dev/test/scan; production servers only pull images.

## Directory layout

```
app/                    FastAPI backend package
  main.py               app factory, lifespan, static/SPA serving, healthz/readyz
  config.py             pydantic-settings (env)
  db.py                 engine, session, migration runner
  migrations/           ordered .sql files, applied by version
  models.py             SQLAlchemy ORM (mirror of migrations)
  schemas.py            Pydantic API DTOs (the API contract types)
  auth.py               argon2 hashing, sessions, require_admin, CSRF double-submit
  audit.py              audit log helper
  errors.py             ApiError + error envelope {error:{code,message,details}}
  scheduler.py          APScheduler jobs (sync, reminders, weekly report, backup, lumi push)
  demo.py               DEMO_MODE synthetic dataset
  util.py
  api/                  routers (thin: parse -> service -> DTO)
  services/             business logic
    bilibili/           Bilibili upstream client (owned by bilibili agent)
    sync.py             followings / watch-history sync orchestration
    ai_classifier.py    OpenAI-compatible classification
    reminders.py        reminder rule engine
    emailer.py          SMTP
    weekly_report.py    HTML weekly report
    feeds.py            Atom feed rendering
    lumirss.py          LumiRSS push adapter
apps/web/               React SPA (Vite)
e2e/                    Playwright suite (demo mode)
deploy/                 compose files, Caddyfile examples
docs/                   research + operations docs
.github/workflows/      CI: test, scan, CodeQL, build/push GHCR on tags
```

## Conventions

- All timestamps: UTC `YYYY-MM-DD HH:MM:SS` strings (SQLite CURRENT_TIMESTAMP format).
- All SQL through SQLAlchemy or parameter binding. No string-built SQL, ever.
- Secrets only from env or the `app_settings` table; never in code, tests, or fixtures.
- Errors: `ApiError(status, code, message)`; responses shaped `{"error": {...}}`.
- Auth: session cookie `biliup_session` (HttpOnly) + CSRF double-submit cookie
  `biliup_csrf` verified by header `X-CSRF-Token` on every mutating request.
- Demo mode (`DEMO_MODE=1`): services never call the network; synthetic data seeds on boot.

## Database schema (v1)

Tables (see `app/migrations/0001_init.sql` for column-level truth):
`admin_users`, `sessions`, `app_settings`, `bilibili_account`, `up_users`,
`groups_local`, `native_group_map`, `videos`, `watch_history`, `ai_suggestions`,
`reminders`, `sync_runs`, `feed_tokens`, `audit_logs`, `backups`, `lumirss_push_log`.

Key relationships: `up_users.group_id -> groups_local.id` (one local group per UP,
NULL = 未分组); `native_group_map` maps a Bilibili native follow-tag to a local
group; `ai_suggestions` holds classification proposals pending human review.

## Scheduler jobs

| Job | Default schedule | Behaviour |
| --- | --- | --- |
| followings sync | every 6h | pull followings, upsert, detect new/missing |
| watch-history sync | every 2h | pull recent history, update last_watched |
| reminder scan | every 30min | evaluate rules, create/dedupe/resolve reminders |
| lumirss push | every 5min | push new videos to LumiRSS when configured |
| weekly report | Mon 08:00 | build + email HTML report |
| backup | daily 03:00 | sqlite backup into data/backups |

## Reminder rules

`stale_uploader`, `long_unwatched`, `never_watched`, `important_unwatched`,
`low_confidence`, `login_expired`, `sync_failed`, `risk_control`, `lumirss_failure`,
`ai_failed`. Deduped by `dedup_key`; auto-resolved when the condition clears.

## Frontend pages

`/login`, `/` dashboard, `/followings` (filter + bulk edit), `/groups`,
`/review` (AI queue), `/reminders`, `/history`, `/weekly-report`,
`/settings` (Account/Bilibili, AI, Notifications, LumiRSS, Feeds, Backups, Audit).
Dark "tech" theme, responsive, zh-CN UI copy.
