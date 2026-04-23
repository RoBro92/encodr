#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/opt/encodr-worker"
PLATFORM="linux"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir) INSTALL_DIR="$2"; shift 2 ;;
    --platform) PLATFORM="$2"; shift 2 ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

if [[ "$PLATFORM" == "macos" ]]; then
  PLIST_PATH="/Library/LaunchDaemons/com.encodr.worker.plist"
  launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
  rm -f "$PLIST_PATH"
else
  SERVICE_PATH="/etc/systemd/system/encodr-worker.service"
  systemctl disable --now encodr-worker.service >/dev/null 2>&1 || true
  rm -f "$SERVICE_PATH"
  systemctl daemon-reload >/dev/null 2>&1 || true
fi

rm -rf "$INSTALL_DIR"

echo "Encodr worker removed from $INSTALL_DIR."
