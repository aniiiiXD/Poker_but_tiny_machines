# TICKET-007 — Catantron swap: Hexchange v2 on the catanatron engine
**Status:** gated (2026-11-04 — watchdog pass: 39/39 hexchange v2 tests, full suite 271/271, ruff clean, allowed-paths verified — pyproject/uv.lock touched only for the orchestrator-approved catanatron dependency)

**Goal:** rebuild `play_hexchange_match` on the **catanatron** library (GPL-3.0,
already installed, PyPI 3.2.1) while preserving OUR contract: same function
signature `play_hexchange_match(bots, seed, decision_cap=500, capture=False)`,
same result schema (points=VP, match_points, winner_seats, faults, errors,
names, log, frames), same observation privacy labels, same fault fallbacks.

**Orchestrator probe findings (verified against the installed 3.2.1):**
- `from catanatron.game import Game`; `Game(players)`; `game.play_tick()`;
  termination = `game.winning_color() is not None` (there is NO `state.is_final`).
- `ActionType`: ROLL, MOVE_ROBBER, DISCARD, BUILD_ROAD, BUILD_SETTLEMENT,
  BUILD_CITY, BUY_DEVELOPMENT_CARD, PLAY_KNIGHT_CARD, PLAY_YEAR_OF_PLENTY,
  PLAY_MONOPOLY, PLAY_ROAD_BUILDING, MARITIME_TRADE, END_TURN.
- **No player-to-player trades** in the engine → the negotiation overlay is
  OURS to preserve (below). **No AI players** ship in this package — our
  baselines stay.
- **Global `random` usage** → run every match under a module-level
  `threading.Lock()` and `random.seed(seed)` at match start (matches serialize
  per worker process; this is what keeps replay-from-seed deterministic).
  Document the trade-off in RULES.md.
- Bots wrap as `catanatron.models.player.Player` subclasses:
  `decide(game, playable_actions)` — project state → our observation dict,
  map our `{"type": ...}` reply → a playable Action; illegal mapping = fault.

**Build requirements**
1. Rename current engine → `backend/arena/games/hexchange/engine_v1.py` (keep
   importable; adapter no longer uses it).
2. `catantron_worker.py` (in-package): the match loop. Auto-execute ROLL
   (chance belongs to the trusted engine) and auto-DISCARD (deterministic
   lowest-half per RULES.md); never show ROLL/DISCARD to bots.
3. **Trade overlay preserved:** before a bot's END_TURN takes effect, inject a
   trade phase — our structured `offer/accept/reject/counter` vocabulary
   (max 3 offers/turn), applied as direct state mutations (resource freqdeck
   deltas via `state.player_state`); logged as public events. No free text.
4. **Observations:** project `state.player_state` + public board per the
   contract visibility table (own hand private; counts/dev-card counts public;
   resource identities of opponents, dev deck hidden). Exact key set frozen in
   RULES.md §Observation before coding.
5. **Termination:** `winning_color()` or decision cap 500 → most VP wins, ties
   share. Auto-discard on 7 (deterministic lowest) — deviation declared.
6. **RULES.md v2 section:** cite catanatron (GPL-3.0, repo link) as the rules
   engine; list deviations (cap termination, auto-discard, overlay trades are
   platform additions, fixed first seat). Add repo-root
   `THIRD_PARTY_NOTICES.md`: catanatron, GPL-3.0, URL, what it is used for.
7. **Tests (test_hexchange.py v2):** determinism under the lock (same seed ⇒
   identical result; two sequential matches don't interfere), resource
   conservation via freqdecks, action mapping (illegal bot replies → faults +
   fallback), overlay trade lifecycle, robber + knight, VP win + cap,
   privacy recording-wrapper, baselines zero-fault matches at 3 and 4 seats,
   SandboxDown propagation.
8. Update `HexchangeAdapter` notes if the interface contract changes —
   registry.py itself stays orchestrator-owned; do not edit it.

**Allowed paths:** `backend/arena/games/hexchange/*`,
`backend/tests/test_hexchange.py`, `THIRD_PARTY_NOTICES.md` (repo root).
**Done-when:** 32+ adapted tests green, full backend suite green, ruff clean on
touched paths, determinism test proves same-seed reproducibility.
