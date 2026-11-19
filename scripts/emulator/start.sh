#!/usr/bin/env bash
# Starts AWS Emulator in the background and waits for the health check.
# The emulator process gets no AWS credentials and IMDS disabled.
set -euo pipefail
PORT="${EMULATOR_PORT:-9297}"
LOG="${EMULATOR_LOG:-$PWD/.emulator/emulator.log}"
mkdir -p "$(dirname "$LOG")"
HEALTH="https://127.0.0.1:${PORT}/__admin/health"

if [ "$(curl -sk -o /dev/null -w '%{http_code}' "$HEALTH" || true)" = 200 ]; then
  echo "emulator already running on ${PORT}"; exit 0
fi

env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN -u AWS_PROFILE \
  AWS_EC2_METADATA_DISABLED=true \
  nohup aws-emulator -p "$PORT" --telemetry off > "$LOG" 2>&1 &
echo $! > "$(dirname "$LOG")/emulator.pid"

start=$(date +%s%3N)
for _ in $(seq 1 120); do
  if [ "$(curl -sk -o /dev/null -w '%{http_code}' "$HEALTH" || true)" = 200 ]; then
    echo "emulator healthy on ${PORT} in $(( $(date +%s%3N) - start )) ms"
    exit 0
  fi
  sleep 0.25
done
echo "emulator did not become healthy"; cat "$LOG"; exit 1
