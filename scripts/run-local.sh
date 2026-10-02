#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export UV_CACHE_DIR="$PWD/var/uv-cache"
uv sync --python 3.12 --extra guardrails --extra local-embeddings
npm --prefix frontend ci --cache "$PWD/var/npm-cache"
npm --prefix frontend run build
exec .venv/bin/uvicorn supportops.api:app --host 127.0.0.1 --port "${PORT:-8000}"
