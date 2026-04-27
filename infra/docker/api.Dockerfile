# syntax=docker/dockerfile:1.7

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY packages/core /app/packages/core
COPY packages/db /app/packages/db
COPY packages/shared /app/packages/shared
COPY apps/api /app/apps/api
COPY VERSION /app/VERSION

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install "psycopg[binary]>=3.1,<4.0" \
    && pip install \
        -e /app/packages/core \
        -e /app/packages/db \
        -e /app/packages/shared \
        -e /app/apps/api

WORKDIR /app/apps/api

CMD ["sh", "-c", "cd /app/packages/db && alembic -c alembic.ini upgrade head && cd /app/apps/api && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
