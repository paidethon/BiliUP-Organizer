# Architecture (frozen contract)

Last updated: 2026-10-01. The database schema and the `/api/v1` contract described
here are the coordination point between all implementation agents. Changing them
requires updating this file in the same commit.

## Stack

- Backend: Python 3.11+, FastAPI, SQLAlchemy 2 (sync), SQLite (WAL), APScheduler.
- Frontend: React 18 + TypeScript + Vite + Tailwind v4 + TanStack Query + react-router + @tanstack/react-virtual.
- Deployment: single versioned Docker image (GHCR), Caddy reverse proxy, `/data` volume for SQLite + backups.
- Everything runs locally in WSL for dev/test/scan; production servers only pull images.

## Directory layout

```
app/                    FastAPI backend package
  main.py               app factory, lifespan, static/SPA serving, healthz/readyz
  config.py             pydantic-settings (env)
  db.py                 engine, session, migration runner
  migrations/           ordered Python modules m0001_*.py …, applied by version
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
    native_sync.py      local-group -> native-tag push (dry run supported)
    ai_classifier.py    OpenAI-compatible structured classification
    classification_jobs.py  persistent full-library classification job runner
    taxonomy.py         category/tag/status-label shared helpers, alias + merge
    memberships.py      many-to-many UP <-> group relations
    undo.py             bulk-operation undo log
    reminders.py        reminder rule engine
    emailer.py          SMTP
    weekly_report.py    HTML weekly report
    feeds.py            Atom feed rendering
    lumirss.py          LumiRSS push adapter
apps/web/               React SPA (Vite); e2e specs in apps/web/e2e/
deploy/                 compose files, Caddyfile examples
docs/                   research + operations docs
.github/workflows/      CI: test, scan, CodeQL, build/push GHCR on tags
```

## Conventions

- All timestamps: UTC `YYYY-MM-DD HH:MM:SS` strings (SQLite CURRENT_TIMESTAMP format).
- All SQL through SQLAlchemy or parameter binding. No string-built SQL, ever.
- Secrets only from env or the `app_settings` table; never in code, tests, or fixtures.
- Errors: `ApiError(status_code, code, message, details=None)`; responses shaped `{"error": {...}}`.
- Auth: session cookie `biliup_session` (HttpOnly) + CSRF double-submit cookie
  `biliup_csrf` verified by header `X-CSRF-Token` on every mutating request.
- Demo mode (`DEMO_MODE=1`): services never call the network; synthetic data seeds on boot;
  the classification job runner simulates batches locally.

## Classification model (v5)

Three independent dimensions:

1. **Primary category** — `groups_local` (the local "分组"). Unlimited count,
   user-managed CRUD + merge + aliases (`group_aliases`). `group_members` is the
   many-to-many membership table; `up_users.group_id` remains the PRIMARY group
   for native-tag sync bookkeeping.
2. **Content tags** — `tags` + `up_tags`, many per UP (机器人 / 硬件 / 摄影 …).
3. **Status labels** — `up_status_labels`, explicit states only
   (`新关注 活跃 断更 长期未看 从未观看 重点关注 待整理 低置信度 无法确定 已取关 吃灰`).
   Derived states such as 断更/从未观看/已取关 stay computed from sync fields and
   are filtered via the `flag` parameter — never stored per UP.

`group_aliases` keeps the AI vocabulary stable: classifier output resolves
through exact name → alias → fuzzy similarity, and a fuzzy hit auto-registers an
alias. `ai_suggestions` carries the structured result (`suggested_tags`,
`previous_group_name`, `evidence`, `provider`, `prompt_version`; status gains
`unclassifiable`).

## Full-library classification jobs

`classification_jobs` is a persistent job row driven by a daemon thread
(`services/classification_jobs.py`): batched (default 20), every batch commits
its cursor + counters, pause/resume/cancel are DB-status transitions checked
between batches, `retry-failures` re-queues failed mids, and startup marks
interrupted `running` jobs as `paused`. `kind=pending` covers UPs with
`ai_status in (none, error)`; `kind=full` covers every non-missing UP.
Completion requires `processed == total`; failed items are retryable.

Confidence workflow (settings `ai`): `>= auto_apply_threshold` (0.90) applied
directly when `auto_apply_enabled`; between `review_threshold` (0.65) and the
auto threshold → pending human review; below → `unclassifiable` + 待整理 status
label, never a guessed category.

## Native-group sync decoupling

Local categories are the source of truth and are unlimited; Bilibili native
tags (upstream cap ~20) are only a projection. Writes happen solely through
explicit pushes (`native_overwrite` manual; `native_incremental` scheduled but
gated off by `sync.native_push_enabled`). Every push supports `dry_run=true`
(remote reads only: would_create/would_delete/would_move/skipped/conflicts).
`full` sync never touches native tags; AI classification completion never does.

## Undo

Bulk operations with local, revertible effects (group moves, tag/status edits,
flags) capture per-UP before-state into `undo_records` (24h expiry) and return
an `undo_id`; `POST /followings/undo/{id}` restores it. Group merges store a
full snapshot. Remote/destructive actions (`native_move`, `unfollow`) are
honest about being non-undoable.

## Database schema (v5)

Tables (column-level truth: `app/models.py` + `app/migrations/m000*_*.py`):
`admin_users`, `sessions`, `app_settings`, `bilibili_account`, `up_users`,
`groups_local`, `group_members`, `group_aliases`, `tags`, `up_tags`,
`up_status_labels`, `native_group_map`, `classification_jobs`, `undo_records`,
`videos`, `watch_history`, `ai_suggestions`, `reminders`, `sync_runs`,
`feed_tokens`, `audit_logs`, `backups`, `lumirss_push_log`.

Migrations are Python modules with an `upgrade(engine)` function, recorded in
`schema_version`; m0005 adds the classification-model tables/columns and
backfills `ai_suggestions.previous_group_name` for old rows.

## Scheduler jobs

| Job | Default schedule | Behaviour |
| --- | --- | --- |
| followings sync | every 6h (setting) | pull followings, upsert, detect new/missing |
| watch-history sync | every 2h | pull recent history, update last_watched |
| native groups sync | every 6h | diff-based incremental push — skipped unless `sync.native_push_enabled` |
| reminder scan | every 24h (setting) | evaluate rules, create/dedupe/resolve reminders |
| lumirss push | every 5min | push new videos to LumiRSS when configured |
| weekly report | Mon 08:00 | build + email HTML report |
| backup | daily 03:00 | sqlite backup into data/backups |

## Reminder rules

`stale_uploader`, `long_unwatched`, `never_watched`, `important_unwatched`,
`low_confidence`, `login_expired`, `sync_failed`, `risk_control`, `lumirss_failure`,
`ai_failed`. Deduped by `dedup_key`; auto-resolved when the condition clears.

## Frontend pages

`/login`, `/` dashboard, `/followings` (paged/all modes, virtual scroll, URL
state, bulk + undo), `/groups` (categories, merge, aliases, tags), `/review`
(suggestion cards + job panel), `/reminders`, `/reminders-config`, `/history`,
`/weekly-report`, `/settings` (AI thresholds, sync & native-push gate, SMTP,
LumiRSS, appearance). Dark glass theme (`--lumi-*` tokens), responsive, zh-CN copy.

The followings list persists display preferences in localStorage
(`biliup.followings.displayMode`, `biliup.followings.pageSize`) and mirrors
filters/sort/mode/page into the URL for shareable, refresh-stable state.
