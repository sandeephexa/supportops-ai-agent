FROM node:22-bookworm-slim AS frontend
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_CACHE_DIR=/tmp/uv-cache
WORKDIR /app
RUN pip install --no-cache-dir uv==0.11.29
COPY pyproject.toml uv.lock ./
COPY backend/ ./backend/
COPY data/ ./data/
ARG LOCAL_EMBEDDINGS=false
RUN if [ "$LOCAL_EMBEDDINGS" = "true" ]; then uv sync --frozen --no-dev --extra guardrails --extra local-embeddings --no-editable; else uv sync --frozen --no-dev --extra guardrails --no-editable; fi
COPY alembic.ini ./
COPY migrations/ ./migrations/
COPY scripts/ ./scripts/
COPY --from=frontend /ui/dist ./frontend/dist
RUN useradd --uid 10001 --create-home supportops && mkdir -p /app/var && chown -R supportops:supportops /app/var
USER supportops
ENV PATH="/app/.venv/bin:$PATH" SUPPORTOPS_ENABLE_GUARDRAILS=true SUPPORTOPS_PROJECT_ROOT=/app SUPPORTOPS_AUTO_CREATE_SCHEMA=false
EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["sh", "scripts/container-start.sh"]
