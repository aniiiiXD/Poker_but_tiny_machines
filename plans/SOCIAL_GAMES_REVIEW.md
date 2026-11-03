# Review of GLM social-games implementation

Review date: 2026-11-01. Verdict: **request changes; Bluff is not ready for an event or real submitted bots**. This reviews the current uncommitted working tree; it does not imply every changed file was authored by GLM. No application code was changed in this review.

**Follow-up:** The findings below were subsequently fixed locally. Regression coverage now includes four-, five- and eight-entrant rounds, legacy replay filtering, match-boundary resets, cap resolution, scoped submission ordering, match-weighted standings, and real sandbox practice and scored rounds for both Bluff tracks. The supplied Bluff model starter's card-ranking bug was also corrected. The full backend suite passed (126 tests); frontend lint and build passed. A separate local browser session verified draft switching/reload and a Bluff baseline practice replay. This update does not imply public deployment or a complete security audit.

## Findings

### P1 — Real Bluff agents are never started

`backend/arena/games/bluff/engine.py:43` never calls `reset()` before `act()` at line 115. `ContainerBot` and `ModelContainerBot` require `reset()` to start their isolated process. Both `worker._practice_game` and `_score_round_game` instantiate fresh bots and immediately enter the engine. Every submitted bot therefore receives repeated `Bot is not running; reset it before use` faults and is replaced by fallback actions; the match can still be scored. GitHub smoke tests hide this because `BluffAdapter.smoke` starts the bot first, and the round test's fake bot doesn't require initialization.

Reproduced with the live `ContainerBot`, starter Bluff source, three baseline bots and `decision_cap=12`: **3 submitted-bot faults**, first error `Bot is not running; reset it before use`. Start/reset every agent at the match boundary, classify initialization infrastructure failures correctly, and test actual source and model bots through real practice and a scored round. Ensure multi-match practice resets state for each match.

### P1 — Replay API leaks hidden game state

`backend/arena/worker.py:54` serializes every result field other than `frames` into replay `summary`, including `log`; `backend/arena/app.py:825` returns that summary through the replay endpoint. Bluff's `log` contains every concealed played card, the full face-down pile, and final private hands (`backend/arena/games/bluff/engine.py:208,239-241`). Tournament replays become public after round commit and logged-out baseline demos can also be public.

Reproduced using an isolated temporary SQLite database: unauthenticated `GET /api/replays/{id}` returned HTTP 200, included `summary.log`, and its first play exposed `cards`. Construct replay summaries from a public allow-list, store privileged logs separately, and ensure existing stored Bluff replays are sanitized at read time or migrated safely. Test the entire serialized API response, not only `frames`.

### P1 — Four-entry and larger Bluff rounds fail

`backend/arena/worker.py:570` calls `adapter.make_baselines(seats - len(primary), ...)` for every table. A full four-player table passes zero, but `backend/arena/games/bluff/baselines.py:123` rejects counts below one. Any round with four or more entrants hits a full table and fails before playing. Reproduced directly: `make_bluff_baselines(0)` raises `ValueError: Bluff has between 1 and 4 baseline strategies.` Allow zero fillers or skip construction when no fillers are needed. Add scored-round tests with 4, 5 and 8 entrants, checking each entrant is scored exactly once per iteration and incomplete tables receive the right fillers.

### P1 — Bluff model sandbox uses poker protocol

`backend/arena/sandbox.py:329-335`: `ModelContainerBot._initial_config()` omits `self.protocol`. The container supervisor defaults to poker and rejects Bluff actions. Reproduced using a ZIP of `backend/starter-model-bluff/`, `ModelContainerBot(..., protocol='bluff')`, and the real Bluff adapter smoke test: `BotError: Bot returned an invalid action`. Include the protocol in model configuration; add a real Docker test for model validation, practice and tournament use, and retain a poker model regression.

### P1 — Switching games can overwrite a draft with the other game's source

`frontend/src/Workshop.tsx:79-94` reads the new game's draft and writes the current render's `source` to that new game's key in separate effects. When switching to a game without a stored draft, `starter.data` can still be the preceding game's source until the asynchronous request clears/resolves; the persistence effect also writes the old source under the new game key. When the new starter arrives, the code sees that stored value and can keep showing the wrong starter. With existing drafts, writes also transiently overwrite the other key. Rework draft loading/persistence so the loaded state is explicitly associated with the selected game and only saved after hydration; migrate the old `arena-draft-source` and `arena-draft-name` keys without losing drafts. Browser-test switching in both directions with fresh and edited drafts, including delayed starter responses and page reloads.

### P2 — Newer submissions in another game/track prevent activation

`backend/arena/worker.py:270-278` checks for any newer validation job or manual submission by team, with no game or track filter. The result is used by both GitHub and model validation. For example, a newer Bluff classic submission can cause a valid Poker model submission to finish accepted but inactive, even when no newer Poker model exists. Scope asynchronous ordering and activation consistently to team + game + track, including queued jobs and manual submissions. Test out-of-order cross-game and cross-track validation alongside same-scope ordering.

### P2 — Bluff standings contradict published scoring

`backend/arena/games/registry.py:186` says Bluff standing is the average match score, while `backend/arena/app.py:487` applies poker's `round score × round number` to every game's event and global leaderboard. A second-round win is weighted twice as heavily as an identical first-round win; results can exceed 1 and standings can change relative to the stated average. Select a game-aware aggregation policy and use match counts where needed to calculate a true mean. Preserve legacy poker ranking and add a multi-round Bluff test with different round scores and unequal match counts.

### P2 — Cap is applied mid-claim and replay omits winners

`backend/arena/games/bluff/engine.py:187-190` can end immediately after a claim, before other players get the promised challenge opportunity. If the claimant has just emptied their hand, cap scoring can award them a win without resolving their potentially false claim. Additionally, `frame('end', ...)` and the audit end record are emitted at lines 238–241 before cap winners are computed at 242–244, so capped replays show `winner_seats: null` despite a scored winner. Reproduced a four-decision match: result winners were `[0, 1, 2, 3]` but end frame winners were `null`. Define a cap boundary that resolves an in-progress claim, compute winners before emitting end records, and test both final-card challenge and capped replay consistency.

## Independent validation

- Backend: `cd backend && uv run python -m pytest -q` — **116 passed**, one Starlette/httpx deprecation warning.
- Frontend: `cd frontend && pnpm lint && pnpm build` — both passed.
- Targeted probes: real `ContainerBot` initialization, real Docker-backed Bluff model smoke, full-table filler boundary, temporary-database unauthenticated replay response, and cap replay consistency — reproduced as described above. Temporary data was removed automatically.
- A full manual browser click-through, actual GitHub App integration, multi-entrant live round and deployment were not performed in this review. Tests passing does not establish the handoff's end-to-end claims because the relevant paths above were not covered.

## Re-review requirements

Fix the findings without destructive changes to existing user data. Add focused regression tests that fail before each fix, including real sandbox tests for both bot tracks and a complete serialized replay privacy assertion. Run the full backend suite, frontend lint/build and the poker + Bluff browser journeys. Preserve all existing uncommitted work and report exact test commands and outcomes.
