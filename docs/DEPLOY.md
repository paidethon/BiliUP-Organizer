# Deployment runbook — up.oouo.top

Target: single server (47.100.64.202), Docker Engine + Compose only.
**The server never builds anything** — it only pulls versioned images from GHCR.
Development, tests, scans and image builds happen locally in WSL / GitHub Actions.

## Layout on the server

```
/opt/biliup-organizer/
├── compose.yaml               # copied from deploy/ (pinned image tag)
├── compose.production.yaml    # overrides: restart policy, resource limits
├── .env                       # 0600, never in git
└── data/                      # SQLite + backups volume
```

## First deployment

1. Push a tag (e.g. `v0.1.0`) → GitHub Actions builds and publishes
   `ghcr.io/<owner>/biliup-organizer:<tag>` after CI is green.
2. On the server: create `/opt/biliup-organizer`, copy the two compose files,
   create `.env` (umask 077, chmod 600) with:
   - `APP_ENV=production`
   - `BOOTSTRAP_ADMIN_USERNAME` / `BOOTSTRAP_ADMIN_PASSWORD` (or leave empty and
     use the first-run `/auth/setup` flow; the password is stored as an argon2 hash)
   - `APP_SECRET_KEY` (random)
   - AI / SMTP / LumiRSS values are optional — everything is also configurable
     in the Settings UI and can be added later.
3. `docker compose -f compose.yaml -f compose.production.yaml pull`
4. `docker compose -f compose.yaml -f compose.production.yaml up -d`
5. Caddy (host-level) reverse-proxies `up.oouo.top` → `127.0.0.1:8066`.
   Back up the existing Caddyfile before editing; `caddy validate` before reload.

## Health checks

```bash
curl -fsS https://up.oouo.top/healthz
curl -fsS https://up.oouo.top/readyz
docker compose -f compose.yaml -f compose.production.yaml ps
docker stats --no-stream
```

## Upgrades

1. Backup SQLite first (in-app Settings → Backups, or `data/backups/`).
2. Bump the image tag in `compose.yaml`, then `pull` + `up -d`.
3. Watch logs; run the smoke checks above. Rollback = re-pin the previous tag
   and `up -d` again (migrations are forward-only; check release notes).

## Backups

- Scheduled: the app creates a consistent SQLite backup into `data/backups/`
  daily at 03:00 UTC; manual backups anytime from the Settings UI.
- Restore: upload a `.db` file via Settings → Backups (integrity-checked,
  previous DB is kept as `*.before-restore.db`), then restart the container.
- Off-host: copy `data/backups/` off the server periodically.

## Security notes

- The app binds to `127.0.0.1:8066` inside the server; only Caddy is public.
- `.env` is 0600 and never leaves the server; no secrets are baked into images.
- The SSH key for the server lives only in the local WSL `~/.ssh/` (0600) and is
  never committed, uploaded or copied into the repository.
