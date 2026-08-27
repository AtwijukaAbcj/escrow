#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
PID_FILE="$ROOT_DIR/run.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "No PID file found at $PID_FILE. Nothing to stop."
  exit 0
fi

PID=$(cat "$PID_FILE")
if [ -z "$PID" ]; then
  echo "PID file is empty. Removing file."
  rm -f "$PID_FILE"
  exit 0
fi

if kill -0 "$PID" >/dev/null 2>&1; then
  echo "Stopping TrustPay.Auth.Api process with PID $PID"
  kill "$PID"
  sleep 2
  rm -f "$PID_FILE"
  echo "Stopped."
else
  echo "Process $PID is not running. Removing stale PID file."
  rm -f "$PID_FILE"
fi
