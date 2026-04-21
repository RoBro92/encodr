FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY packages/shared /app/packages/shared
COPY packages/core /app/packages/core
COPY apps/worker-agent /app/apps/worker-agent
COPY VERSION /app/VERSION

RUN pip install --no-cache-dir \
    -e /app/packages/shared \
    -e /app/packages/core \
    -e /app/apps/worker-agent

WORKDIR /app/apps/worker-agent

CMD ["python", "-m", "app.main"]
