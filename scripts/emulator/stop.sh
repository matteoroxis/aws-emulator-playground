#!/usr/bin/env bash
# Stops the emulator started by start.sh (SIGTERM: clean shutdown, in-memory state is discarded).
PID_FILE="${EMULATOR_LOG:-$PWD/.emulator/emulator.log}"
PID_FILE="$(dirname "$PID_FILE")/emulator.pid"
if [ -f "$PID_FILE" ]; then
  kill "$(cat "$PID_FILE")" 2>/dev/null || true
  rm -f "$PID_FILE"
fi
