#!/bin/sh
set -eu
alembic upgrade head
exec uvicorn supportops.api:app --host 0.0.0.0 --port 8000
