# GLM work report — Stack Theory social games (foundation + Bluff slice)

**Author:** GLM (`hyde/glm-5.3-flash`), coding agent via OpenCode
**Date:** 2026-11-01
**Task:** Implement `plans/SOCIAL_GAMES_IMPLEMENTATION_PLAN.md` — M0–M3 (multi-game
foundation and the full Bluff vertical slice). M4 (UNO) and M5 (original game)
were explicitly out of scope for this pass.
**Status:** implemented and verified locally. **Nothing committed, nothing
deployed.** Awaiting review.

## 0. Provenance — read this before reading the diff

The working tree already contained a large **uncommitted pass by Codex**
(another coding agent): the Stack Theory rebrand, the model-track subsystem
(16 MiB projects, model sandbox image, showcases), the GitHub App/OAuth
integration, lease-fenced jobs, the new test files, `SubmissionSources.tsx`,
and assorted docs/experiments. Per the plan, GLM **preserved that work
untouched** and implemented M0–M3 on top of it. Consequences for review:

- Files like `app.py`, `worker.py`, `db.py`, `sandbox.py` contain **both**
  Codex's prior WIP and GLM's changes — do not attribute the whole diff to
  either agent.
- Everything Codex left uncommitted still is uncommitted. GLM committed
  nothing and reset nothing; the two passes are interleaved in one tree.
- The baseline GLM captured before starting (87 tests passing) already
  included Codex's work, so all test deltas reported below are GLM's.

---

## 1. Behavior summary

From the existing local app a user can now:

1. Open `/workshop` and switch between **Poker** and **Bluff** via game tabs
   (the choice persists in the URL as `?game=`).
2. Get the **game-matching starter kit** — editor source, interface, guide,
   and ZIP download (`/api/starter?game=bluff`, `/api/starter/download?game=bluff`).
3. **Submit a bot for a specific game** (`POST /api/submissions {name, source,
   game}`). Activation is scoped per team + game + track: activating a Bluff
   bot never deactivates the team's Poker bot, and vice versa.
4. **Practice** — Bluff runs a full 4-seat match (user bot in seat 0 plus three
   built-in strategies, or a pure baseline demo that needs no Docker). Poker
   practice is byte-for-byte unchanged.
5. **Watch a game-appropriate replay** — Bluff replays show per-seat card
   counts, declared ranks, pass/challenge decisions, pile size, and the
   revealed challenged batch only, with stepping, playback, and a
   decision log. Poker replays render exactly as before.
6. **Join a Bluff event and see game-specific results** — 4-seat rounds with
   labelled unscored baseline fillers, per-round seat rotation from the round
   seed, scoring v1 (win = 1, loss = 0, cap ties share the point), standings
   as average match score. Poker's 8-seat scoring is untouched.
7. Discover implemented games via `GET /api/games`; every game-taking endpoint
   returns a clear 422 for unknown or version-mismatched IDs and **never
   silently falls back to poker**.

All three submission routes (manual source, model upload, GitHub
repository/branch) carry explicit game association and are validated with the
game's own sandbox smoke harness. Legacy API calls that omit `game` default to
poker; legacy database rows are interpreted as poker.

## 2. Changed files

### New (all GLM)

| File | Purpose |
|---|---|
| `GAMES_CONTRACT.md` | M0 frozen contracts: registration, observation/action schemas, result/replay schemas, compatibility rules |
| `backend/arena/games/__init__.py` | Package; re-exports registry symbols |
| `backend/arena/games/registry.py` | Trusted `GameSpec` registry, `get_game()`, `list_games()`, `PokerAdapter` / `BluffAdapter` |
| `backend/arena/games/bluff/engine.py` | Stack Theory Bluff v1 deterministic engine |
| `backend/arena/games/bluff/baselines.py` | Honest / Random / Counter / Liar baselines |
| `backend/starter-bluff/agent.py`, `README.md` | Documented single-file starter |
| `backend/starter-model-bluff/agent.py`, `weights.json`, `README.md` | Model-track starter (NumPy, bounded weights) |
| `backend/tests/test_bluff.py` | 15 engine tests (rules, determinism, privacy, fallbacks) |
| `backend/tests/test_games.py` | 11 API/integration tests incl. live-Docker bluff sandbox validation |
| `backend/tests/test_migrations.py` | Populated pre-change DB upgraded twice; activation scoping |

### Modified by GLM (on top of Codex's uncommitted WIP — shared files contain both passes)

| File | GLM's change |
|---|---|
| `backend/arena/db.py` | Additive migrations: `game_id` + `rules_version` on `submissions` and `events`; `game_id` on `replays` and `github_repositories`. Seed-event insert converted to named columns. |
| `backend/arena/app.py` | `GET /api/games`; `game` params on starter/submissions/practice/admin-events/leaderboard; scoped activation; adapter-driven rules block; additive `game` fields on events, submissions, replays |
| `backend/arena/worker.py` | `deactivate_active()` (team+game+track); `insert_replay()` versioned game wrapper + named columns; round freeze validates game and freezes game-specific bots; practice dispatch + `_practice_game`; smoke via adapters for GitHub/model validation; `_score_round_game` (4-seat bluff rounds) beside the untouched poker `score_round` body; `seed_exhibition` inserts named |
| `backend/arena/sandbox.py` | `protocol` parameter on `ContainerBot`/`ModelContainerBot` + `reply_validator_for()` strict allow-lists (poker default identical) |
| `backend/sandbox/supervisor.py` | Protocol-aware `valid_action()` / `clean_result()`; config carries `protocol` (default poker — old host + new image and new host + old image both stay compatible for poker) |
| `backend/arena/model_projects.py` | `game` query param on submissions and model-starter download; named-column insert |
| `backend/arena/github_integration.py` | `game` on repository connect, stored on `github_repositories`, carried in webhook/sync validation payloads |
| `backend/arena/cli.py` | `--game` flag for event creation; named-column insert |
| `backend/tests/test_{worker,live_round,api,github_models}.py` | Positional INSERTs on altered tables converted to named columns with `'poker', 1` defaults (behavior unchanged) |
| `frontend/src/Workshop.tsx` | Game tabs, per-game starter/drafts (localStorage keys per game)/submissions/practice/save |
| `frontend/src/SubmissionSources.tsx` | Game threaded through GitHub connect and model upload/starter |
| `frontend/src/Replay.tsx` | Game branch; new `BluffReplay` component |
| `frontend/src/Rules.tsx` | Bluff v1 rules section, labelled as a selected variant |
| `frontend/src/PublicPages.tsx` | Replay list says "match" for bluff, "hands" for poker |
| `frontend/src/arena.css` | Game-tab and bluff-replay styles (reduced-motion respected) |

**Local environment only:** rebuilt `campus-arena-bot:local` and
`campus-arena-model:local` from `backend/sandbox/` (the supervisor change
requires it). This is a local build, not a deployment. (The model sandbox
subsystem itself — `Dockerfile.model`, `MODEL_IMAGE`, 16 MiB limits — is
Codex's prior work; GLM only threaded the game protocol through it.)

## 3. Contract highlights (full detail in `GAMES_CONTRACT.md`)

Bluff observation (protocol 1) — own hand plus public state only:

```json
{"protocol": 1, "game": "bluff", "rules_version": 1, "seat": 2,
 "players": [{"seat": 0, "name": "Honest", "count": 4, "out": false}],
 "hand": ["Ac", "3d"], "required_rank": "A", "pile_size": 7,
 "turn": {"type": "challenge", "claimant": 1, "rank": "A", "count": 3},
 "history": [{"type": "play", "seat": 1, "rank": "A", "count": 3, "pile_size": 3}],
 "decision_number": 12, "decision_cap": 500}
```

Actions: `{"type": "play", "cards": [...]}` (1–4 owned, distinct IDs) or
`{"type": "challenge"}` / `{"type": "pass"}`. Invalid or timed-out decisions
record a fault and fall back deterministically (sorted-lowest card, or pass).
`SandboxDown` remains an infrastructure failure and aborts unscored.

Result: `points` (win 1 / cap ties split), `winner_seats`, `terminal_reason`,
`faults`, `errors`, `final_rank`, privileged audit `log` (contains true
batches and final hands), and public `frames` (no hidden cards; revealed
batches only where `challenged_by` is set).

## 4. Key decisions and rationale

1. **Poker hot path left literally untouched.** Existing tests monkeypatch
   `worker.play_table` / `worker.ContainerBot`; I kept the poker branches of
   `practice` and `score_round` byte-identical and added game branches beside
   them, dispatching on the job payload's `game_id`. Risk to existing behavior:
   minimal; verified by the full suite.
2. **Transport needed to learn about games.** The supervisor hard-validated
   poker's action vocabulary and rebuilt replies, so a bluff bot could never
   survive the sandbox. I extended the supervisor config with a `protocol`
   field and strict per-game allow-lists (`valid_action`, `clean_result`),
   mirroring the same allow-lists host-side (`reply_validator_for`). Poker
   remains the default in both directions of image/host skew.
3. **Activation scoped, not migrated to a new table.** `submissions.active`
   stays the single source of truth, now written only through
   `deactivate_active(team, game, track)` at all three activation sites.
   Legacy rows become poker through column defaults — no data rewrite.
4. **Bluff reuses the poker sandbox images.** Bots are stdlib Python with the
   same limits; a separate image would add cost without isolation benefit.
   The model image works for bluff model projects unchanged.
5. **Bluff scored rounds share the publication machinery's guarantees**
   (lease fencing, atomic job completion, score-event chain with `game_id` in
   the payload, hand logs + seating metadata per match, replay publication
   only after the round commits) but are a separate code path so the poker
   loop stays frozen.

## 5. Tests run and results

| Command | Result |
|---|---|
| Baseline before any change: `uv run python -m pytest -q` | **87 passed** (Docker running; live tests genuinely executed) |
| Final: `uv run python -m pytest -q` | **116 passed, 0 failed** (15 bluff engine, 11 games/API, 2 migration; includes live poker round, live bluff sandbox validation, live model sandbox tests) |
| `pnpm lint` | pass |
| `pnpm build` | pass (Bluff replay + game tabs included in bundle) |
| Live smoke, real server on `127.0.0.1:8002` with isolated `ARENA_DATA_DIR`: `/api/health`, `/api/games`, `POST /api/practice {"game":"bluff","matches":1}`, job poll, replay fetch, poker exhibition check | all correct — completed bluff match, 383 public frames, 0 faults, replay carries `game`/`protocol`/`names`; poker exhibition replay intact (`game: poker`) |

Test data hygiene: every test uses `tmp_path` / `ARENA_DATA_DIR`; the user's
`backend/data/` database was never opened for writing by any test or by me.

## 6. Failures hit during development (all resolved)

1. **Sandbox rejected bluff actions** ("Bot returned an invalid action") —
   poker vocabulary was enforced in both the supervisor and the host
   transport. Fixed with the protocol-aware design above; caught by the
   live-Docker bluff test.
2. **`ModelContainerBot` didn't accept the new `protocol` kwarg** — signature
   updated, model live tests re-verified.
3. **Positional `INSERT` breakage after additive columns** — converted all
   affected inserts (production and test fixtures) to named columns, exactly
   the hazard the plan warned about.
4. **My own test bugs** — scripted deals that didn't match real seeded deals
   (fixed by mirroring the deal or picking seeds deterministically), a
   shared-cookie-jar trap where registering a second user swapped the session
   (fixed with a second `TestClient`), a missing event entry row, and an
   over-broad challenge-sequence assertion. All test-side; no engine changes.

## 7. Incomplete paths, known risks, follow-ups

- **M4 (UNO prototype) and M5 (original game) not started** — by scope
  agreement; the foundation (registry, adapters, scoped activation, game-aware
  transport) is what they would build on.
- **Image skew on other machines:** a stale `campus-arena-bot:local` +
  current host will reject bluff bots ("invalid action") because the old
  supervisor ignores the `protocol` field and validates poker. Run
  `make sandbox` after pulling. Poker is unaffected in both skew directions.
- **Bluff scored-round coverage is one table deep.** Multi-table chunking of
  5+ entrants is implemented (same chunk loop as poker, seat size 4) but not
  covered by a dedicated test; cross-round seat rotation is documented and
  derives from the per-round seed but has no explicit assertion.
- **No live-Docker bluff *model*-track validation test yet** — the model path
  dispatch is tested in-process; a Docker variant of
  `test_live_bluff_sandbox_validation` for a zipped bluff project would close
  the last gap.
- **Frontend smoke tests** (BACKLOG #14) remain unimplemented — not required
  by this plan.
- **One pre-existing pytest warning** (Starlette/httpx deprecation) — present
  in the baseline, not introduced by this work.
- **Git state:** per the plan ("stop after local implementation and
  verification; the user will ask for a separate review") nothing is
  committed. The working tree intentionally contains Codex's preserved
  uncommitted pass interleaved with this implementation — see §0 Provenance.
  If a clean attribution matters for the review, the practical options are:
  (a) Codex reviews and commits its own WIP first, then GLM's diff becomes
  committable on top, or (b) one combined commit crediting both passes.

## 8. Manual click-through for the reviewer

1. `colima start --profile bot-arena --cpu 2 --memory 3 --disk 12`, then
   `make sandbox` (rebuild for the protocol-aware supervisor), `make dev`.
2. **Poker regression:** `http://127.0.0.1:5173/` → Workshop stays on Poker by
   default → save a bot → *Practice with my bot* → replay renders the poker
   table exactly as before. Existing events, replays, and leaderboards load.
3. **Bluff:** Workshop → **Bluff** tab (URL becomes `?game=bluff`) → starter
   guide shows the Bluff interface → *Try baseline demo* (works logged out) →
   job shows 4 seats with points and no chips column → *Open replay* → step
   through claims, challenges, pile pickups, and the revealed batch →
   *Rules* page now has the "Bluff · the second arena" section.
4. **Activation scoping:** save a bot under Poker and another under Bluff —
   both show *active* in their own tab; saving a new Poker bot deactivates
   only the Poker one.
5. **API spot checks:** `GET /api/games`; `GET /api/leaderboard?game=bluff`
   (empty until a bluff event scores); `GET /api/starter?game=chess` → 422.
6. **Scoring a bluff event:** `uv run python -m arena.cli create-event
   "Bluff open" --game bluff --tables 1 --hands 1` (needs the sandbox image),
   join with a team holding an active bluff bot, then
   `run-round <event_id>`; event page shows "Stack Theory Bluff v1" and the
   bluff scoring rules block.

Per the plan: this is a local implementation verified locally — **not**
labelled production-ready, not deployed, and public-hosting hardening remains
a separate gate.
