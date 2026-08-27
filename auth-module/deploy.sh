#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
PROJECT_PATH="$ROOT_DIR/src/TrustPay.Auth.Api/TrustPay.Auth.Api.csproj"
PUBLISH_DIR="$ROOT_DIR/publish"
LOG_DIR="$ROOT_DIR/logs"
PID_FILE="$ROOT_DIR/run.pid"
ENV_FILE="$ROOT_DIR/.env"
CONFIGURATION="${1:-Release}"

if ! command -v dotnet >/dev/null 2>&1; then
  echo "ERROR: dotnet is not installed or not available on PATH."
  exit 1
fi

if [ ! -f "$PROJECT_PATH" ]; then
  echo "ERROR: Project file not found: $PROJECT_PATH"
  exit 1
fi

mkdir -p "$PUBLISH_DIR"
mkdir -p "$LOG_DIR"

if [ -f "$ENV_FILE" ]; then
  echo "Loading environment variables from $ENV_FILE"
  set -o allexport
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +o allexport
fi

echo "Publishing TrustPay.Auth.Api ($CONFIGURATION) to $PUBLISH_DIR"
dotnet publish "$PROJECT_PATH" -c "$CONFIGURATION" -o "$PUBLISH_DIR"

cd "$PUBLISH_DIR"

if [ -f "$PID_FILE" ]; then
  OLD_PID=$(cat "$PID_FILE")
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" >/dev/null 2>&1; then
    echo "Stopping existing process with PID $OLD_PID"
    kill "$OLD_PID"
    sleep 2
  fi
fi

export ASPNETCORE_ENVIRONMENT="Production"

nohup dotnet TrustPay.Auth.Api.dll > "$LOG_DIR/trustpay-auth.out" 2> "$LOG_DIR/trustpay-auth.err" < /dev/null &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"
echo "Auth API started with PID $NEW_PID"
echo "Logs: $LOG_DIR/trustpay-auth.out"
