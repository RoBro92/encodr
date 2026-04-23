#!/usr/bin/env bash
set -euo pipefail

SERVER_URL=""
WORKER_KEY=""
PAIRING_TOKEN=""
REGISTRATION_SECRET=""
DISPLAY_NAME=""
INSTALL_DIR="/opt/encodr-worker"
QUEUE="remote-default"
SCRATCH_DIR="/opt/encodr-worker/scratch"
MEDIA_MOUNTS=""
PYTHON_COMMAND="python3"
RELEASE_REF="main"
PREFERRED_BACKEND="cpu_only"
ALLOW_CPU_FALLBACK="true"
PLATFORM="linux"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --server-url) SERVER_URL="$2"; shift 2 ;;
    --worker-key) WORKER_KEY="$2"; shift 2 ;;
    --pairing-token) PAIRING_TOKEN="$2"; shift 2 ;;
    --registration-secret) REGISTRATION_SECRET="$2"; shift 2 ;;
    --display-name) DISPLAY_NAME="$2"; shift 2 ;;
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --queue) QUEUE="$2"; shift 2 ;;
    --scratch-dir) SCRATCH_DIR="$2"; shift 2 ;;
    --media-mounts) MEDIA_MOUNTS="$2"; shift 2 ;;
    --python-command) PYTHON_COMMAND="$2"; shift 2 ;;
    --release-ref) RELEASE_REF="$2"; shift 2 ;;
    --preferred-backend) PREFERRED_BACKEND="$2"; shift 2 ;;
    --allow-cpu-fallback) ALLOW_CPU_FALLBACK="$2"; shift 2 ;;
    --platform) PLATFORM="$2"; shift 2 ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$SERVER_URL" || -z "$WORKER_KEY" ]]; then
  echo "--server-url and --worker-key are required." >&2
  exit 1
fi

if [[ -z "$PAIRING_TOKEN" && -z "$REGISTRATION_SECRET" ]]; then
  echo "Provide either --pairing-token or --registration-secret." >&2
  exit 1
fi

if [[ -z "$DISPLAY_NAME" ]]; then
  DISPLAY_NAME="$WORKER_KEY"
fi

if [[ "$RELEASE_REF" == v* ]]; then
  ARCHIVE_URL="https://codeload.github.com/RoBro92/encodr/tar.gz/refs/tags/$RELEASE_REF"
else
  ARCHIVE_URL="https://codeload.github.com/RoBro92/encodr/tar.gz/refs/heads/$RELEASE_REF"
fi

SRC_DIR="$INSTALL_DIR/source"
VENV_DIR="$INSTALL_DIR/venv"
TOKEN_FILE="$INSTALL_DIR/worker.token"
RUNTIME_CONFIG_FILE="$INSTALL_DIR/runtime-config.json"
ENV_FILE="$INSTALL_DIR/worker-agent.env"
RUN_SCRIPT="$INSTALL_DIR/run-worker-agent.sh"
UNINSTALL_SCRIPT="$INSTALL_DIR/uninstall-worker-agent.sh"

mkdir -p "$INSTALL_DIR" "$SCRATCH_DIR"
rm -rf "$SRC_DIR"
mkdir -p "$SRC_DIR"

curl -fsSL "$ARCHIVE_URL" | tar -xz -C "$SRC_DIR" --strip-components=1

"$PYTHON_COMMAND" -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install \
  -e "$SRC_DIR/packages/shared" \
  -e "$SRC_DIR/packages/core" \
  -e "$SRC_DIR/apps/worker-agent"

install -m 755 "$SRC_DIR/infra/scripts/uninstall-worker-agent-unix.sh" "$UNINSTALL_SCRIPT"

cat >"$ENV_FILE" <<EOF
export ENCODR_WORKER_AGENT_API_BASE_URL="$SERVER_URL"
export ENCODR_WORKER_AGENT_KEY="$WORKER_KEY"
export ENCODR_WORKER_AGENT_DISPLAY_NAME="$DISPLAY_NAME"
export ENCODR_WORKER_AGENT_QUEUE="$QUEUE"
export ENCODR_WORKER_AGENT_SCRATCH_DIR="$SCRATCH_DIR"
export ENCODR_WORKER_AGENT_MEDIA_MOUNTS="$MEDIA_MOUNTS"
export ENCODR_WORKER_AGENT_TOKEN_FILE="$TOKEN_FILE"
export ENCODR_WORKER_AGENT_RUNTIME_CONFIG_FILE="$RUNTIME_CONFIG_FILE"
export ENCODR_WORKER_AGENT_FFMPEG_PATH="ffmpeg"
export ENCODR_WORKER_AGENT_FFPROBE_PATH="ffprobe"
export ENCODR_WORKER_AGENT_PREFERRED_BACKEND="$PREFERRED_BACKEND"
export ENCODR_WORKER_AGENT_ALLOW_CPU_FALLBACK="$ALLOW_CPU_FALLBACK"
export ENCODR_WORKER_AGENT_PAIRING_TOKEN="$PAIRING_TOKEN"
export ENCODR_WORKER_AGENT_REGISTRATION_SECRET="$REGISTRATION_SECRET"
EOF

cat >"$RUN_SCRIPT" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/worker-agent.env"
exec "$(dirname "$0")/venv/bin/python" -m app.main loop 999999
EOF
chmod +x "$RUN_SCRIPT"

echo "Registering worker with Encodr..."
set +e
source "$ENV_FILE"
"$VENV_DIR/bin/python" -m app.main register
REGISTER_STATUS=$?
set -e
if [[ $REGISTER_STATUS -ne 0 ]]; then
  echo "Worker registration failed with exit code $REGISTER_STATUS." >&2
  exit 10
fi

echo "Waiting for pairing confirmation..."
set +e
"$VENV_DIR/bin/python" -m app.main heartbeat
HEARTBEAT_STATUS=$?
set -e
if [[ $HEARTBEAT_STATUS -ne 0 ]]; then
  echo "Worker pairing validation failed with exit code $HEARTBEAT_STATUS." >&2
  exit 11
fi

if [[ "$PLATFORM" == "macos" ]]; then
  PLIST_PATH="/Library/LaunchDaemons/com.encodr.worker.plist"
  cat >"$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>com.encodr.worker</string>
    <key>ProgramArguments</key>
    <array>
      <string>$RUN_SCRIPT</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
  </dict>
</plist>
EOF
  launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
  launchctl load "$PLIST_PATH"
else
  SERVICE_PATH="/etc/systemd/system/encodr-worker.service"
  cat >"$SERVICE_PATH" <<EOF
[Unit]
Description=Encodr worker agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=$RUN_SCRIPT
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now encodr-worker.service
fi

echo "Encodr worker paired successfully."
echo "Encodr worker installed."
echo "Worker key: $WORKER_KEY"
echo "Server URL: $SERVER_URL"
echo "Uninstall command: sudo $UNINSTALL_SCRIPT --install-dir $INSTALL_DIR --platform $PLATFORM"
