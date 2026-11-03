# Stack Theory social games: implementation handoff

**Audience:** coding agents implementing the work and the reviewer checking it afterward.

**Product direction:** familiar social games played by submitted AI agents. Deliver an end-to-end **Bluff (Cheat / I Doubt It)** vertical slice first, then a separately versioned **UNO rules prototype**. Poker must remain playable. After those work, consider Gin Rummy, Hearts, Spades and an original social card game.

This is a local-development plan, not a claim that new games or public hosting already exist. Existing changes in this checkout are uncommitted user work: inspect `git status`, preserve them, and do not reset, clean, overwrite or treat the current tree as disposable. Do not publish, deploy, change AWS/GitHub settings, or add paid services as part of this plan.

## 1. Definition of done

From the existing local app, a user can select Poker or Bluff, obtain the matching starter kit, submit and activate a compatible bot, play practice matches against baselines, view a game-appropriate replay, join an event and see game-specific results. A later milestone delivers the same journey for the UNO prototype. Existing poker bots, event history, APIs and replays continue to work. All three game types are accurately labelled; no placeholder or unimplemented game appears playable.

```text
game selection -> starter kit -> submit bot -> practice -> replay
                                      |                       ^
                                      v                       |
                               enter event -> rounds -> standings

Poker API/legacy bot -> poker runner ------------------------------+
Bluff bot -----------> Bluff runner ------------------------------+
UNO prototype bot ---> UNO runner --------------------------------+
```

Local Docker execution is for development and controlled pilots. These milestones do not make execution of arbitrary public submissions production-safe. Keep the existing production hardening plan as a separate gate.

## 2. Current code and compatibility hazards

- `backend/arena/engine.py::play_table` runs poker and defines its existing observation/action contract. Existing bot inputs must remain unchanged.
- `backend/arena/worker.py::practice`, `score_round`, `insert_replay`, `smoke_bot` and the eight-seat tournament loop are poker-specific. `hand_logs`, `points`, `chips`, `hands` and frames carry poker assumptions.
- `backend/arena/db.py` initializes SQLite with additive migrations and many positional `INSERT INTO ... VALUES` statements. Changing columns without updating every insert risks breakage. Preserve existing rows and test upgrades against a populated old-schema fixture, not only a fresh database.
- `submissions.active` is currently scoped to the whole team, and GitHub/model validation has poker-specific smoke checks. Introduce game-specific activation and validation without deactivating another game's bot. Existing classic/model tracks remain distinct from game choice.
- GitHub repositories, uploaded source and model projects all need explicit game association; webhook validation must use the associated game. Preserve existing repo links, versions, permissions and asynchronous ordering semantics.
- `frontend/src/Workshop.tsx`, `Replay.tsx`, `Rules.tsx`, `api.ts` and the poker table components embed poker terminology and shapes. Inspect callers before editing. Existing API consumers must tolerate additive fields; old requests default to poker.
- Event scheduling freezes submission IDs and uses leases, infrastructure-failure handling, score-chain auditing and transactional result publication. Preserve these guarantees and avoid publishing partial rounds or private information.

## 3. Scope and milestones

### M0 — Freeze the contracts before parallel coding

1. Record current branch and dirty-tree status. Read `CONTRACT.md`, the relevant backend modules and existing tests. Never include existing credentials or local data in commits.
2. Create versioned written schemas and examples for game registration, bot observations/actions, result, replay and submission compatibility. Agree exact API fields before separate agents touch shared files. Existing poker `Agent.act(observation)` remains byte-for-byte compatible; introduce a game-specific `Agent.act(observation)` for new games using versioned JSON data, not a changed wrapper imposed on old bots.
3. Settle whether first Bluff delivery includes source and GitHub bots plus model projects: target all three using existing transport and sandbox limits, but do not claim a route works until its own tests pass. Event input must distinguish `game_id`, rules version and `track`.
4. Capture a baseline using the existing test commands and an isolated test data directory. Report pre-existing failures; do not delete the user's database or interrupt their running app.

### M1 — Small multi-game foundation

- Add a trusted game registry, e.g. `backend/arena/games/registry.py`, keyed by a stable game ID and immutable rules version. Explicitly enumerate allowed adapters; user submissions cannot choose executable server-side modules or supply engine code.
- Define a narrow interface for game config, seat count, validated agent observations/actions, run-to-completion, results and replay projection. `poker` wraps the existing engine without changing its contract; adapters choose and validate game-specific fallbacks. Seed and all game state stay in the trusted engine, never in agent observations.
- Persist `game_id`, `rules_version`, and where needed protocol and replay versions using additive metadata tables or safe migrations. Legacy records are interpreted as poker. Decide one source of truth for active submissions keyed by team + game + track; migrate current active poker records consistently and update all source, model and GitHub activation paths in the same change. Keep a deterministic compatibility path for legacy API calls, where omitted game means poker. Avoid relying on column order in new inserts.
- Pin game/rules version, runtime/image digest, immutable submission IDs/hashes, game configuration and seed in each queued round. Validate they agree with the event and reject incompatible submissions before queueing. Existing in-flight/legacy jobs must continue with their original semantics.
- Add `GET /api/games` to return only implemented games and their supported versions/tracks. Add optional, backward-compatible game fields to submission, practice, event, starter, job and replay endpoints as needed. Return a clear 4xx for an unknown/unsupported game or incompatible bot; never silently fall back to poker for an explicitly supplied ID.
- Keep score results scoped by event and game. Do not sum Bluff results into the current cross-event poker leaderboard without an explicit compatible definition. Seeded event and old practice responses retain their existing shape.
- Preserve `SandboxDown` as an infrastructure failure; no untrusted source code executes in the API or trusted engine. Bound bot message sizes and timeouts. Preserve privacy, job ownership, lease fencing, immutable round freeze, atomic result publication, score-chain audit and retry behavior.

### M2 — Bluff engine: precise v1 rules

Implement the following *Stack Theory Bluff v1* variant. Document it as a selected variant, not the only official Bluff ruleset.

- Four seats; standard 52-card deck, shuffled once using a private seed; deal all cards round-robin. Suit and rank are represented internally by unique card identities. Aces precede 2, then 3 through King, then Ace again. Seat 0 starts with required rank Ace.
- On a turn, the active player places 1–4 cards from their own hand face down and claims they are all the current required rank. They may lie. Other players see only the declared rank, count and public game history; hidden cards are not broadcast.
- Every other player gets a challenge decision in clockwise order, beginning with the next seat. The first challenge stops the sequence. Decisions are sequential and visible; a player whose turn to decide has not occurred cannot see a future decision. If everyone passes, the play remains face down.
- On a challenge, inspect the latest played batch: if any card differs from the claimed rank, the player who made the claim takes the entire face-down pile; otherwise the challenger takes it. Only the challenged batch is revealed publicly, not older unchallenged cards in the pile. Then advance required rank by one and play passes to the next seat after the claimant, regardless of challenge outcome.
- A player who empties their hand wins only after all challenge decisions resolve, and only if their hand is still empty. If a challenge makes them pick up the pile, play continues. One winner per match. Set a bounded decision count, e.g. 500, to avoid endless cycles. At the cap, fewest cards wins; ties are shared. Store terminal reason, ranks and faults.
- Accept explicit, ownership-checked card IDs in the active player's action and `challenge`/`pass` for challenge decisions. Handle duplicate or unowned cards as invalid. At an invalid action or timeout, record a fault and use a deterministic legal fallback: first card in a stable sorted own-hand order for a play; `pass` for a challenge. No hidden cards, seed, deck order, opponent hands, previous face-down pile or unrevealed actions enter an agent's observation or public replay.
- Use independent baseline agents including honest-first, random-legal and a simple count-aware challenger. Provide a documented single-file starter and model starter; they must never rely on hidden state.

### M3 — Bluff full vertical slice

1. Implement practice with four appropriate seats, optional owned compatible submission, baseline fill, matching sandbox track, game-specific limits and deterministic seeded results. Smoke validation must cover both a play decision and a challenge decision in a sandbox, including GitHub and model submission paths.
2. Extend event creation/entry, round freezing and scheduling for four-seat Bluff. The scoring convention for v1 is **1 for a win, 0 for a loss, split 1 equally among tied winners**; event standing is average match score. Report match count and faults separately. Seat rotation and scheduling must be documented and tested; avoid giving one primary entrant multiple scored seats in one match. Fill incomplete tables with labelled unscored baselines. Do not change poker's eight-seat scoring.
3. Expose versioned replay frames that show card counts, declared ranks, challenge decisions, pile size and revealed challenged batches. Support stepping and playback. Keep practice replay ownership checks and delay tournament publication until the whole round is committed; never reveal unchallenged hidden cards in a public replay. Do not include raw seed, unredacted logs, private hands or secret payloads in public job results, errors, lists or summaries.
4. Add a clear game selector and Bluff instructions, sample bot, practice controls, results, and replay. Reuse established style, keyboard access, mobile layout and reduced-motion behavior. Existing poker table/replay remains functional.

### M4 — UNO prototype, independently versioned

Prototype the familiar UNO experience locally, with an exact source-backed version of the rules written and reviewed before coding: specify deck composition, 2–4 player setup, legal plays, action-card effects, draw and playable-draw behavior, chosen color, draw-four legality/challenge, UNO declaration, two-player behavior, turn direction, deck exhaustion, end-of-hand scoring, fault fallback and termination cap. Cite the selected Mattel rules and explicitly list any rule deviations; do not substitute house rules silently.

Implement its own game adapter, observations/action schema, starter agents, replays, practice, scoring and event path using the foundation established for Bluff. Add tests for wild colors, reverse/skip, draw effects, card conservation and last-card edge cases. Do not call a Crazy Eights implementation UNO or claim official status. Review trademark, artwork and other permissions before public branded release; do not copy proprietary art or imply endorsement. If that review is unresolved, keep branded prototype local and use original placeholder visual assets, clearly labelled.

### M5 — Original game (design only until user picks it)

Develop a short rules proposal and testable prototype concept for a social card game such as **Double Trouble**. Define turn sequence, challenge priority, action effects, scoring and termination; conduct balance testing before treating it as a deliverable. It is inspired by existing mechanics; do not claim novelty without further research. No need to implement this milestone before Bluff and UNO work.

## 4. Suggested coding-agent assignments

Work serially where interfaces or shared files overlap. Do not have multiple agents edit `app.py`, `worker.py`, `db.py` or the same frontend component concurrently.

1. **Coordinator / contracts owner:** M0, shared schemas, compatibility decisions, integration and final `app.py`, `worker.py`, `db.py` changes. Own schema migration and review every integration.
2. **Bluff engine agent:** isolated `backend/arena/games/bluff/` engine, baseline bots, starter kits and engine tests against the agreed contract; no shared API/DB edits.
3. **Frontend agent:** game catalog and Bluff display/replay components against committed or agreed mock schemas; avoid touching shared files until coordinator integrates.
4. **UNO prototype agent, later:** rules document and isolated engine/tests after the contracts are settled. No proprietary assets; no public deployment.

Each agent reports changed files, assumptions, exact commands/results, known failures and any contract changes. Integrate one bounded change at a time into the existing working tree; do not use destructive git commands or overwrite others' uncommitted work. Coordinator runs end-to-end tests after integration.

## 5. Required verification and reviewer checklist

- **Migration:** upgrade a populated pre-change database twice; old users, active poker bots, GitHub connections, events, scores and replays survive, with idempotent mappings. Fresh initialization works too. Test same team activating one bot per game/track, and freeze the correct ID in each round.
- **Poker regression:** existing poker API, source/model/GitHub submission, practice, scheduled round, scoring, replay privacy and sandbox tests pass. Confirm old API requests/response fields and starter contract still work.
- **Bluff rules:** deterministic shuffle/replay for a fixed seed and fixed action sequence; changing a seed can change the deal; conservation of all 52 cards; legal/illegal plays; truthful and false challenges; simultaneous claim-ending timing; challenge priority; passing; wraparound; final-card challenge; cap ties; fallbacks; no duplicated cards or illegal states.
- **Privacy:** adversarial agents, users and spectators cannot obtain other hands, face-down plays, engine seed, deck order or unrevealed pile through observations, legal-action lists, job payloads, replay endpoints, summaries, error messages or public logs. Separate public replay data from privileged audit data.
- **Integration:** source and model submissions plus GitHub validation route to the correct game and reject wrong-game payloads; cross-team access denied; no user code runs on host. Practice and multi-team scored rounds finish, display correct game-specific replays, and survive worker failure/retry without double scoring. A missing sandbox must fail unscored.
- **UI:** responsive game selection, starter download, submission, practice, standings and replay flows; no dead buttons; keyboard/reduced motion. Test old poker and new Bluff in a browser.
- **UNO:** add targeted tests from M4 only when implementing it, and test the exact selected rules and disclosed deviations.
- **Commands:** from the repo root, run `make test` (backend pytest, frontend lint and build). Run focused tests while developing and report exact failures. Use isolated test data; do not replace real seeded data. If Docker integration tests cannot run, report them as not run, not passed.

## 6. Handoff back for review

Provide: concise behavior summary; list of changed files and migration notes; API/schema examples; the exact tests run and results; any unimplemented paths and known risks; and a manual click-through for Poker and Bluff. Keep the diff reviewable and do not label it production ready. Stop after local implementation and verification; the user will ask for a separate review.
