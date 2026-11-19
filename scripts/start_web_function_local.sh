#!/usr/bin/env bash
# Runs the Web Function's HTTP server as a local process, the same way Lambda would start it,
# with DynamoDB calls going to the emulator. The emulator does not run Web Function code yet
# (its endpoint answers 501), so this is how the e2e suite reaches the Web Function's code.
set -euo pipefail
: "${TABLE_NAME:?TABLE_NAME must be set (run tools/deploy.py first)}"
PORT="${WEB_LOCAL_PORT:-18080}"
mkdir -p .emulator

AWS_LAMBDA_HTTP_ENDPOINT="127.0.0.1:${PORT}" nohup node functions/web/src/server.js \
  > .emulator/web-function.log 2>&1 &
echo $! > .emulator/web-function.pid

for _ in $(seq 1 40); do
  if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    echo "web function listening on ${PORT}"
    if [ -n "${GITHUB_ENV:-}" ]; then echo "WEB_LOCAL_URL=http://127.0.0.1:${PORT}" >> "$GITHUB_ENV"; fi
    exit 0
  fi
  sleep 0.25
done
echo "web function did not start"; cat .emulator/web-function.log; exit 1
