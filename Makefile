.PHONY: install dev web-install web-dev web-build test lint format e2e e2e-server scan up down

PY = uv run
WEB = apps/web

install: ## install backend deps
	uv sync

web-install: ## install frontend deps
	cd $(WEB) && npm install --no-fund --no-audit

dev: ## run backend dev server (demo-capable)
	$(PY) uvicorn app.main:app --host 127.0.0.1 --port 8066 --reload

web-dev: ## run frontend dev server (proxies /api to :8066)
	cd $(WEB) && npm run dev

web-build: ## build frontend into apps/web/dist
	cd $(WEB) && npm run build

test: ## run backend tests
	$(PY) pytest -q

lint: ## ruff check + format check
	$(PY) ruff check .
	$(PY) ruff format --check .

format:
	$(PY) ruff format .
	$(PY) ruff check --fix .

e2e-server: ## start backend in demo mode on :8067 for e2e
	DEMO_MODE=1 APP_ENV=test DATA_DIR=.e2e-data ENABLE_SCHEDULER=0 \
		$(PY) uvicorn app.main:app --host 127.0.0.1 --port 8067

e2e: ## run Playwright e2e suite
	cd $(WEB) && npx playwright test

scan: ## local security scans (needs gitleaks/trivy/osv-scanner installed)
	gitleaks detect --source . --no-git -v || true
	trivy fs --scanners vuln,secret,misconfig . || true
	osv-scanner scan source -r . || true

up: ## run full stack locally via docker compose
	docker compose -f deploy/compose.yaml up -d --build

down:
	docker compose -f deploy/compose.yaml down
