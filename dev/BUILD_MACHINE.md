# The Build Machine — multi-agent engine factory

Design for building all remaining Stack Theory game engines with a fleet of
coding agents. Frozen 2026-11-03. Companion to `GAMES_CONTRACT.md` and
`plans/SOCIAL_GAMES_IMPLEMENTATION_PLAN.md`.

## Roster

| # | Agent | Role | May write | Never touches |
|---|---|---|---|---|
| ① | **Orchestrator** | owns contracts, writes tickets, merges, releases | shared files: `app.py`, `worker.py`, `supervisor.py`, `db.py`, `GAMES_CONTRACT.md` | — (that's the job) |
| ② | **Deck agent** | shared token engine: deck/shuffle/hands/draw/discard/piles | `backend/arena/games/common/*`, `backend/tests/test_deck.py` | everything else |
| ③ | **UNO agent** | engine + baselines + starters + visibility table | `backend/arena/games/uno/*`, its tests | shared files |
| ④ | **Rummy agent** | same, 13-card Indian Rummy | `backend/arena/games/rummy/*` | shared files |
| ⑤ | **Hearts agent** | same, 4-seat trick avoidance | `backend/arena/games/hearts/*` | shared files |
| ⑥ | **Catan agent** | same + trade overlay (structured offer/accept/counter) | `backend/arena/games/catan/*` | shared files |
| ⑦ | **Shared-module watcher** | reads every diff, extracts duplicated motifs into shared libs, files dedup tickets | nothing (tickets only) | code |
| ⑧ | **Breakage watchdog** | runs suites + review-checklist gates; files P1/P2 tickets | nothing (tickets only) | code |
| ⑨ | **Keeper** | slow lane: docker builds, full suites, sandbox batches, retry/resume ledger | `dev/` ops artifacts | game code |

## The machine

```
                          ┌─────────────────────────────┐
                          │        YOU (human)          │
                          │   approves milestones only  │
                          └──────────────┬──────────────┘
                                         │  "go" / "stop"
                          ┌──────────────▼──────────────┐
                          │       ① ORCHESTRATOR        │
                          │ · owns GAMES_CONTRACT v2    │
                          │ · writes task tickets       │
                          │ · ONLY writer of shared     │
                          │   files (app.py, worker.py, │
                          │   supervisor.py, db.py)     │
                          │ · merges + tags releases    │
                          └──┬──────┬──────┬──────┬─────┘
              tickets        │      │      │      │       (serial on shared files;
            ┌────────────────┘      │      │      └──────────────────┐
            ▼                       ▼      ▼                         ▼
   ┌─────────────────┐    ┌────────────────┐ ┌───────────────┐ ┌─────────────────┐
   │ ② DECK AGENT    │    │ ③ UNO AGENT    │ │ ④ RUMMY AGENT │ │ ⑤ HEARTS AGENT  │
   └────────┬────────┘    └───────┬────────┘ └──────┬────────┘ └───────┬─────────┘
            ▼                     ▼                 ▼                  ▼
     games/common/          games/uno/        games/rummy/       games/hearts/

   ┌─────────────────┐
   │ ⑥ CATAN AGENT   │   games/catan/ — board graph, dice, robber,
   │ + trade overlay │   negotiation edges. Parallel from ticket #1.
   └────────┬────────┘
            ▼  every builder emits: engine + baselines + starters +
            │  graph visibility table + contract-conformance tests

   ════════════════════════ FEEDBACK LOOPS ════════════════════════
   ⑦ SHARED-MODULE WATCHER — dedup motifs → tickets to ①
   ⑧ BREAKAGE WATCHDOG — suites + leak/protocol/determinism gates → P1 tickets
   ⑨ KEEPER — docker builds, long suites, batches; retry/resume ledger
```

## Life of one ticket

```
① ticket ──▶ builder codes in isolation ──▶ ⑧ gates (tests, leak scan, protocol,
        ▲                                    determinism) ──fail──▶ P1 ticket back
        │                                                        │ pass
        └──────────────────────◀───────────────────────────────── ▼
                              ⑦ extracts shared motifs? ──▶ ① integrates shared
                              files + supervisor edge vocabulary ──▶ ⑨ full suite +
                              docker ──▶ 🏁 game registered in /api/games
```

## Rules of engagement

1. **One writer of shared files** — only ①. (The Codex/GLM interleave lesson, made structural.)
2. **Contract before tickets** — a game agent starts only after its graph
   visibility table (`public | private(seat) | hidden-until(event)` per
   field) is frozen in the contract. The P1 replay leak died here; keep it dead.
3. **Watchers never edit; they file tickets.**
4. **Deck agent ships first** — ③④⑤ block on it; ⑥ runs parallel.
5. **Supervisor edge vocabulary merged per game by ①** at integration time
   (`reply_validator_for` + supervisor `valid_action`/`clean_result`).
6. **Every engine repeats the Bluff invariants**: seeded deterministic walk,
   bounded path length (decision cap), fault→deterministic fallback,
   `SandboxDown` = infrastructure, no hidden state in observations/replays.

## Game graph map (what each builder implements)

| Game | Chance source | Hidden tokens | Termination | Motif |
|---|---|---|---|---|
| UNO | deck draw | hands + wild color | first empty hand | draw–discard loop |
| Rummy 13-card | deck draw | hands + stock | first valid declaration | draw–discard + meld check |
| Hearts | deck deal | hands + passes | 13 tricks (structurally bounded — no artificial cap) | trick cycle |
| Catan-style | dice + dev deck | hands + dev deck + intent | fixed VP target | race graph + negotiation overlay |

## Build order

`② deck` → `③ uno` → `④ rummy` → `⑤ hearts` → `⑥ catan`
(uno before rummy: smaller contract; rummy inherits its draw–discard motif.)

## Ticket board

Tickets live in `dev/tickets/` — one file each: goal, allowed paths, done-when,
test commands. Status: `queued → in-progress → gated → integrated | blocked`.

## 🔥 Token burn meter

`dev/token_burn.sh` ticks every 15 s, appending to `dev/burn.log`:

```
HH:MM:SS 🔥 ≈N tokens burnt (bytes: B)
```

Estimate = bytes written/changed in the repo since machine start ÷ 4
(4 chars ≈ 1 token). It meters **artifact burn** — docs, engines, tests.
Conversation tokens have no meter in here, so treat the number as the
visible exhaust of the factory, not the total furnace. Hehehehehehehe.
