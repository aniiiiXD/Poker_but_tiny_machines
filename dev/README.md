# dev/ — the build machine's workshop

- `BUILD_MACHINE.md` — the multi-agent factory: roster, diagram, rules, roadmap
- `token_burn.sh` — 🔥 token burn meter (15 s ticks → `burn.log`)
- `burn.log` — live burn readings (append-only)
- `tickets/` — one file per task; status: queued → in-progress → gated → integrated

Run the meter: `bash dev/token_burn.sh &` (already running if `burn.log` grows).
Read the fire: `tail -f dev/burn.log`
