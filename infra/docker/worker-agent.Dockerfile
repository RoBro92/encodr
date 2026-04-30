# syntax=docker/dockerfile:1.7

FROM python:3.12-slim

RUN apt-get update \
    && packages="ffmpeg libva-drm2 libva2 mesa-va-drivers vainfo" \
    && arch="$(dpkg --print-architecture)" \
    && if [ "$arch" = "amd64" ] || [ "$arch" = "i386" ]; then packages="$packages intel-media-va-driver"; fi \
    && for package in libvpl2 libmfx1; do if apt-cache show "$package" >/dev/null 2>&1; then packages="$packages $package"; fi; done \
    && apt-get install -y --no-install-recommends $packages \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY packages/shared /app/packages/shared
COPY packages/core /app/packages/core
COPY apps/worker-agent /app/apps/worker-agent
COPY VERSION /app/VERSION

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install \
        -e /app/packages/shared \
        -e /app/packages/core \
        -e /app/apps/worker-agent

WORKDIR /app/apps/worker-agent

CMD ["python", "-m", "app.main"]
