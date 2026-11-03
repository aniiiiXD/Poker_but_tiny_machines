#!/bin/bash
# dev/agents.sh — status of every agent in the Stack Theory build machine.
# Usage: bash dev/agents.sh            (one shot)
#        bash dev/agents.sh --watch    (refresh every 10 s)
cd "$(dirname "$0")/.." || exit 1

ticket_status() { grep -m1 '^\*\*Status:\*\*' "dev/tickets/$1" 2>/dev/null | sed 's/\*\*Status:\*\* //; s/ ·.*//'; }
dot() {
  case "$1" in
    active*) printf '🟢' ;;
    in-progress*) printf '🟡' ;;
    queued*) printf '⚪' ;;
    blocked*) printf '⛔' ;;
    *) printf '🟣' ;;
  esac
}

meter=$(pgrep -fl token_burn.sh | head -1)
testing=$(pgrep -fl pytest | head -1)
building=$(pgrep -fl "docker build" | head -1)
burn=$(tail -1 dev/burn.log 2>/dev/null | grep '🔥' | tail -1)

deck=$(ticket_status TICKET-001-deck.md)
uno=$(ticket_status TICKET-002-uno.md)
rummy=$(ticket_status TICKET-003-rummy.md)
hearts=$(ticket_status TICKET-004-hearts.md)
catan=$(ticket_status TICKET-005-catan.md)

active=0; queued=0; standby=0
count() { case "$1" in active*) active=$((active+1));; in-progress*) active=$((active+1));; queued*|blocked*) queued=$((queued+1));; *) standby=$((standby+1));; esac; }

render() {
  echo "STACK THEORY BUILD MACHINE — $(date '+%a %H:%M:%S')"
  echo "-------------------------------------------------------------------------"
  printf '%-3s %-22s %-34s %s\n' '#' 'AGENT' 'ROLE' 'STATUS'
  orb1=🟢; count "active"
  printf '%-3s %-22s %-34s %s %s\n' '①' 'ORCHESTRATOR' 'contracts · merge · releases' "$orb1 active (GLM session)"
  printf '%-3s %-22s %-34s %s %s\n' '②' 'DECK' 'shared token engine' "$(dot "$deck") ${deck:-unknown} (TICKET-001)"; count "$deck"
  printf '%-3s %-22s %-34s %s %s\n' '③' 'UNO' 'game engine' "$(dot "$uno") ${uno:-unknown} (TICKET-002)"; count "$uno"
  printf '%-3s %-22s %-34s %s %s\n' '④' 'RUMMY' 'game engine' "$(dot "$rummy") ${rummy:-unknown} (TICKET-003)"; count "$rummy"
  printf '%-3s %-22s %-34s %s %s\n' '⑤' 'HEARTS' 'game engine' "$(dot "$hearts") ${hearts:-unknown} (TICKET-004)"; count "$hearts"
  ct=$(ticket_status TICKET-007-catantron.md)
  printf '%-3s %-22s %-34s %s %s\n' '⑥' 'CATAN' 'catantron engine swap' "$(dot "$ct") ${ct:-unknown} (TICKET-007)"; count "$ct"
  fe=$(ticket_status TICKET-006-frontend.md)
  printf '%-3s %-22s %-34s %s %s\n' '⑩' 'FRONTEND' 'panels · tabs · wording' "$(dot "$fe") ${fe:-unknown} (TICKET-006)"; count "$fe"
  wd="standing-by"; [ -n "$testing" ] && { wd="scanning (pytest live)"; }
  printf '%-3s %-22s %-34s %s %s\n' '⑦' 'MODULE WATCHER' 'motif dedup → tickets' '🟣 '"$wd"; standby=$((standby+1))
  bd="standing-by"; [ -n "$building" ] && bd="building image"
  printf '%-3s %-22s %-34s %s %s\n' '⑧' 'BREAKAGE WATCHDOG' 'gates · P1 tickets' "🟣 $bd"; standby=$((standby+1))
  kp="standing-by"
  printf '%-3s %-22s %-34s %s %s\n' '⑨' 'KEEPER' 'long jobs · retry ledger' "🟣 $kp"; standby=$((standby+1))
  echo "-------------------------------------------------------------------------"
  [ -n "$meter" ] && m="🔥 meter running (pid $(echo "$meter" | awk '{print $1}'))" || m="💤 meter NOT running (bash dev/token_burn.sh &)"
  echo "LIVE: $m"
  [ -n "$burn" ] && echo "      last: $burn"
  [ -n "$testing" ] && echo "      ⏳ pytest in flight · $([ -n "$building" ] && echo '⏳ docker build in flight')"
  echo "TOTAL: 10 agents · $active active · $queued queued · $standby standing-by"
}

if [ "$1" = "--watch" ]; then
  while true; do clear; render; sleep 10; done
else
  render
fi
