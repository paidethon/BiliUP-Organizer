# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1: build the React SPA (Vite) into static assets
# ---------------------------------------------------------------------------
FROM node:22-alpine AS web

WORKDIR /src

# Install exactly the locked dependency tree (layer cached on lockfile change)
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-fund --no-audit

COPY apps/web/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: runtime (FastAPI backend + pre-built SPA)
# ---------------------------------------------------------------------------
FROM python:3.12-slim

# Official uv binary from the astral-sh image (pinned release)
COPY --from=ghcr.io/astral-sh/uv:0.12.20 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Backend dependencies first (cached layer; rebuilds only when the lockfile moves)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application code + the SPA built in stage 1 (served by FastAPI at WEB_DIST)
COPY app/ ./app/
COPY --from=web /src/dist ./web

ENV WEB_DIST=/app/web \
    DATA_DIR=/data \
    APP_HOST=0.0.0.0 \
    APP_PORT=8066 \
    PATH="/app/.venv/bin:$PATH"

# Run as an unprivileged user; /data is the volume mount point
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app app \
 && mkdir -p /data \
 && chown -R app:app /app /data

USER app

EXPOSE 8066

# No curl in the image on purpose — use Python's stdlib
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8066/healthz', timeout=4).status == 200 else 1)"]

ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8066"]
