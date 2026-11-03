#!/bin/bash
# 🔥 dev/burn_once.sh — one-shot burn reading (the 15 s ticker lives in the
# orchestrator's turn-by-turn reports; call this any time for a live number).
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || exit 1
SESSIONS="dev/session_log.txt"

diff_bytes=$(git diff HEAD 2>/dev/null | wc -c | tr -d ' ')
tmp="dev/.burn_tmp_once"
: > "$tmp"
git ls-files --others --exclude-standard -z 2>/dev/null | xargs -0 stat -f%z 2>/dev/null >> "$tmp" || true
new_bytes=$(awk '{s+=$1} END {print s+0}' "$tmp")
rm -f "$tmp"
total=$((diff_bytes + new_bytes))
[ "$total" -lt 0 ] && total=0
atokens=$((total / 4))

spawned=$(grep -c '^spawned' "$SESSIONS" 2>/dev/null); [ -z "$spawned" ] && spawned=0
done_n=$(grep -c '^done' "$SESSIONS" 2>/dev/null); [ -z "$done_n" ] && done_n=0
running=$((spawned - done_n)); [ "$running" -lt 0 ] && running=0
engine=$((done_n * 120000 + running * 60000))
grand=$((engine + atokens))

echo "🔥 ≈${grand} tokens burnt  (engine est: ${engine} · artifacts: ${atokens})"
echo "   sessions: ${spawned} spawned · ${done_n} done · ${running} running · bytes: ${total}"
