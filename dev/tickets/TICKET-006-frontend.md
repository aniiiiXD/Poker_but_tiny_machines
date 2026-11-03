# TICKET-006 — Frontend agent: game tabs, leaderboards, wording pass
**Status:** gated (2026-11-03 — lint + build green, allowed-paths verified; footer wording fixed by orchestrator)

**Goal:** the UI currently speaks Poker everywhere and has half a game selector.
Make it multi-game native.

**Scope (frontend only — `frontend/src/*`, no backend, no git):**
1. **Leaderboard tabs** — `/leaderboard` gets per-game tabs (driven by
   `GET /api/games`): Poker (default, current behavior) | Bluff | (future games
   appear automatically). Each tab fetches `GET /api/leaderboard?game=<id>`.
   Empty state for a game with no scored events: honest copy — "No <Game>
   rounds scored yet. The floor is open." Never fabricate standings.
2. **Event pages speak the right game** — kill the hardcoded poker wording:
   event detail/list must not say "hands"/"Maximum hands" for non-poker games.
   Use the event's `game` + the detail endpoint's `rules` block to render
   game-correct labels (poker: hands/blinds/payouts; bluff: matches/decision
   cap/rank cycle; uno: matches; hexchange: VP/turn). Events list cards get a
   small game badge (use `variant`).
3. **Wording pass** — audit user-facing strings for game-wrongness and tone:
   practice copy, buttons, notices, empty states, the Workshop tab texts.
   Consistent vocabulary: poker = hands/chips; bluff = matches + claims;
   uno = matches; hexchange = matches + VP. Keep the brand voice
   (competitive, tactile, no casino promises, no invented hype).
4. **Home games panel** — small "The games" strip on the landing page from
   `GET /api/games` (name + one-liner + links: workshop-with-tab, rules).
   Reuse existing panel/card classes; no new visual language.

**Constraints:** reuse established classes (`game-tabs`, `panel`, `list-row`),
keyboard access, visible focus, reduced-motion safe, mobile + 2560 layouts.
Do not restructure routing in `main.tsx` beyond what tabs require. Do not
touch any backend file or another agent's game packages. Lint + build must pass.

**Done-when:** `pnpm lint` + `pnpm build` green; every game-wrong string found
by grepping "hands"/"chips" outside poker context is fixed or game-gated; a
poker leaderboard and a bluff leaderboard tab render (bluff tab shows the
honest empty state until events score).
