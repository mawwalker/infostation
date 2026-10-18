#!/usr/bin/env bash
# Daily entry point for cron / systemd. Safe to run several times a day: completed runs are skipped.
#   scripts/run_daily.sh                 # session decided by config (auto)
#   scripts/run_daily.sh --session recap
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$HOME/.nvm/versions/node/$(ls "$HOME/.nvm/versions/node" 2>/dev/null | tail -1)/bin:/usr/local/bin:/usr/bin:$PATH"
mkdir -p data/logs
log="data/logs/$(date +%F_%H%M).log"
if uv run infostation run "$@" >"$log" 2>&1; then
  echo "ok: $log"
else
  code=$?
  echo "FAILED (exit $code): $log" >&2
  tail -30 "$log" >&2
  exit $code
fi
