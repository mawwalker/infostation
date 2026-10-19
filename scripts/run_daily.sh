#!/usr/bin/env bash
# Daily entry point for cron / systemd. Safe to run several times a day: completed runs are skipped.
#   scripts/run_daily.sh                     # session decided by New York time (auto):
#                                            #   trading day before 09:30 ET → premarket X brief, after 16:15 ET → recap video
#   scripts/run_daily.sh --session premarket
#
# Optional settings (in .env):
#   AUTO_FIX=1             on failure, let agy diagnose/fix per the infostation-daily skill, then resume once
#   NOTIFY_SCRIPT=/path    executable called as: NOTIFY_SCRIPT <ok|failed> <message>  (e.g. send to Telegram)
set -uo pipefail
cd "$(dirname "$0")/.."
NODE_BIN="$(ls -d "$HOME"/.nvm/versions/node/*/bin 2>/dev/null | tail -1)"
export PATH="$HOME/.local/bin:${NODE_BIN:+$NODE_BIN:}/usr/local/bin:/usr/bin:/bin:$PATH"
if [ -f .env ]; then set -a; . ./.env; set +a; fi

mkdir -p data/logs
stamp="$(date +%F_%H%M)"
log="data/logs/${stamp}.log"

notify() {  # $1 = ok|failed, $2 = message
  command -v notify-send >/dev/null 2>&1 && notify-send -a InfoStation "InfoStation: $1" "$2" 2>/dev/null || true
  if [ -n "${NOTIFY_SCRIPT:-}" ] && [ -x "${NOTIFY_SCRIPT}" ]; then "${NOTIFY_SCRIPT}" "$1" "$2" || true; fi
}

run_once() { uv run infostation run "$@" >>"$log" 2>&1; }

# Daily bars sometimes appear a few minutes late after the close: wait and retry instead of failing.
run() {
  local i
  for i in 1 2 3; do
    run_once "$@" && return 0
    tail -5 "$log" | grep -q "no price bars" || return 1
    [ "$i" -lt 3 ] && { echo "price data not ready yet, retrying in 15 min" >>"$log"; sleep 900; }
  done
  return 1
}

if run "$@"; then
  out="$(grep -o 'done → .*' "$log" | tail -1)"
  echo "ok: $log"; notify ok "${out:-run complete}"
  exit 0
fi

echo "FAILED: $log" >&2
tail -30 "$log" >&2

if [ "${AUTO_FIX:-0}" = "1" ] && command -v agy >/dev/null 2>&1; then
  fixlog="data/logs/${stamp}_autofix.log"
  echo "AUTO_FIX: asking agy to diagnose (log: $fixlog)" >&2
  agy -p "InfoStation 的定时任务失败了，失败日志在 $log。请按 .agents/skills/infostation-daily/SKILL.md 的流程排查：
读日志和最新的 runs/*/run.log、state.json，运行 uv run infostation doctor 找原因；如果是代码或采集器的问题就修复并运行
uv run pytest -q 确认；如果是外部原因（网络、数据源暂时不可用、显卡被占用），不要改代码。
不要删除 runs/ 或 data/，不要上传或发布任何内容，不要修改 .env。最后用三五句话说明原因和你做了什么。" \
    --model "${AUTO_FIX_MODEL:-gemini-4-argon-medium}" --dangerously-skip-permissions --print-timeout 2400s >"$fixlog" 2>&1
  echo "AUTO_FIX: retrying" >>"$log"
  if run "$@"; then
    echo "ok after auto-fix: $log"; notify ok "recovered after auto-fix (see $fixlog)"
    exit 0
  fi
fi

notify failed "see $log"
exit 1
