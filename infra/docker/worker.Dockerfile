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
COPY apps/worker /app/apps/worker
COPY VERSION /app/VERSION

RUN pip install --no-cache-dir "psycopg[binary]>=3.1,<4.0" \
    && pip install --no-cache-dir \
        -e /app/packages/core \
        -e /app/packages/db \
        -e /app/packages/shared \
        -e /app/apps/worker

WORKDIR /app/apps/worker

CMD ["python", "-m", "app.main"]
