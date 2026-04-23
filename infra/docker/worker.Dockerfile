FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && packages="ffmpeg libva-drm2 libva2 mesa-va-drivers vainfo" \
    && arch="$(dpkg --print-architecture)" \
    && if [ "$arch" = "amd64" ] || [ "$arch" = "i386" ]; then packages="$packages intel-media-va-driver"; fi \
    && apt-get install -y --no-install-recommends $packages \
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
