# syntax=docker/dockerfile:1.7

FROM python:3.12-slim

ARG ENCODR_UID=10001
ARG ENCODR_GID=10001

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid "${ENCODR_GID}" encodr \
    && useradd --uid "${ENCODR_UID}" --gid encodr --create-home --home-dir /home/encodr --shell /usr/sbin/nologin encodr

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

RUN mkdir -p /data /temp /media \
    && chown -R encodr:encodr /app /data /temp /media /home/encodr

USER encodr
WORKDIR /app/apps/api

CMD ["sh", "-c", "cd /app/packages/db && alembic -c alembic.ini upgrade head && cd /app/apps/api && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
