UV_CACHE_DIR := $(CURDIR)/var/uv-cache
export UV_CACHE_DIR
.PHONY: setup dev build start test lint eval e2e migrate
setup:
	uv sync --python 3.12 --extra guardrails
	cd frontend && npm ci --cache ../var/npm-cache
build:
	cd frontend && npm run build
start:
	uv run --extra guardrails uvicorn supportops.api:app --host 127.0.0.1 --port 8000
dev:
	uv run --extra guardrails uvicorn supportops.api:app --host 127.0.0.1 --port 8000 --reload
test:
	uv run --extra guardrails pytest -q
lint:
	uv run --extra guardrails ruff check backend scripts migrations
	uv run --extra guardrails ruff format --check backend scripts migrations
eval:
	uv run --extra guardrails python scripts/evaluate.py
e2e:
	cd frontend && PLAYWRIGHT_BROWSERS_PATH=../var/playwright E2E_BASE_URL=http://127.0.0.1:8000 npm run test:e2e
migrate:
	uv run --extra guardrails alembic upgrade head
