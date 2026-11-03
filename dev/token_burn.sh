#!/bin/bash
# 🔥 token_burn.sh v2 — ticks every 15 s with two numbers:
#   artifacts: measured (bytes written/changed in repo ÷ 4)
#   engine:    ESTIMATE (subagent context churn — logged sessions × ~120k done,
#              ~60k while running; conversation tokens unmetered)
# Appends to dev/burn.log. Run: bash dev/token_burn.sh &
REPO="$(cd "$(dirname "$0")/.." && pwd)"
BASE="$REPO/dev/.burn_baseline"
LOG="$REPO/dev/burn.log"
TMP="$REPO/dev/.burn_tmp"
SESSIONS="$REPO/dev/session_log.txt"
cd "$REPO" || exit 1

if [ ! -f "$BASE" ]; then echo 0 > "$BASE"; fi
base=$(cat "$BASE")
echo "🔥 burn meter v2 started $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG"

while true; do
  # — artifact burn (measured) —
  diff_bytes=$(git diff HEAD 2>/dev/null | wc -c | tr -d ' ')
  : > "$TMP"
  git ls-files --others --exclude-standard -z 2>/dev/null | xargs -0 stat -f%z 2>/dev/null >> "$TMP" || true
  new_bytes=$(awk '{s+=$1} END {print s+0}' "$TMP")
  rm -f "$TMP"
  total=$((diff_bytes + new_bytes - base))
  [ "$total" -lt 0 ] && total=0
  atokens=$((total / 4))

  # — engine burn (estimated from session ledger) —
  spawned=$(grep -c '^spawned' "$SESSIONS" 2>/dev/null || echo 0)
  done_n=$(grep -c '^done' "$SESSIONS" 2>/dev/null || echo 0)
  running=$((spawned - done_n)); [ "$running" -lt 0 ] && running=0
  engine=$((done_n * 120000 + running * 60000))
  grand=$((engine + atokens))

  echo "$(date '+%H:%M:%S') 🔥 ≈${grand} tokens burnt (engine est: ${engine} · artifacts: ${atokens} · sessions: ${spawned} spawned, ${running} running)" >> "$LOG"
  sleep 15
done
