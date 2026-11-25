#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 BACKUP_DIR" >&2
  exit 2
fi

BACKUP_DIR="$(cd "$1" && pwd)"
VOLUME="${PAPERPROOF_VOLUME:-paperproof_paperproof_data}"
IMAGE="${PAPERPROOF_IMAGE:-paperproof:local}"
TEMP_VOLUME="paperproof_restore_tmp"

docker compose stop app
docker volume create "$TEMP_VOLUME" >/dev/null

cleanup() {
  docker volume rm "$TEMP_VOLUME" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "Restoring $BACKUP_DIR into a temporary volume"
docker run --rm \
  -v "$TEMP_VOLUME":/app/data \
  -v "$BACKUP_DIR":/backup:ro \
  --entrypoint paperproof \
  "$IMAGE" restore --from /backup --data-dir /app/data

echo "Replacing the live volume contents"
docker run --rm \
  -v "$VOLUME":/target \
  -v "$TEMP_VOLUME":/source \
  alpine:3.20 \
  sh -c 'find /target -mindepth 1 -maxdepth 1 -exec rm -rf {} + && cp -a /source/. /target/'

docker compose start app
echo "Restore complete. The app is starting with the restored data."
