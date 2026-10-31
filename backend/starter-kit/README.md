# Campus Arena starter kit

Implement `class Agent` with `act(self, observation: dict) -> dict` in a single
UTF-8 Python file. Standard library only. The platform supplies the game engine.
An Agent instance lasts one table. It is recreated before the next table.

Actions: `{"action":"check"}`, `{"action":"call"}`, `{"action":"fold"}`,
`{"action":"raise", "amount": observation["min_raise"]}`.
Raise amount is your TOTAL contribution on the current street, not the increment.
Always consult `legal_actions`; `min_raise`/`max_raise` are null if raising is illegal.

Observation fields: hand, street, seat, button, hole_cards, board, pot, stack,
to_call, min_raise, max_raise, legal_actions, players, history.
Cards use rank+suit strings, e.g. As, Td, 7h. Opponent cards, identities and the
private shuffle seed are never included. Players expose seat, stack, bet, folded.

Upload via the Workshop, then run a practice table. Source limit: 100 KiB.
The current pilot accepts one source file, not dependencies or model weights.
AI coding assistance is allowed outside play. Network access is disabled during
play. No external model/API calls. Return within the configured decision deadline
(default 1 ms, measured by the isolated supervisor including IPC/scheduling).
Startup has a separate allowance. Errors/timeouts/illegal actions check if legal,
otherwise fold. The sandbox terminates a timed-out worker for the rest of the table.

Scoring: eight-bot tables, 2,000 chips each, blinds 10/20 doubling every 25 hands.
Points by finish: 8, 5, 3, 2, 1, 0, 0, 0. At the hand limit, remaining points use
exact Independent Chip Model allocation. Six rounds carry weights 1 through 6.
The local founding pilot uses 8 table iterations per round / 50 hands to keep
local resource use modest. Operators can configure up to 10,000 iterations and
200 hands. This independent event uses its own announced Hold'em rules; it is
not Sequoia's unreleased event variant or official SDK.

Run `python simulate.py` from this kit to practice against local copies of the
platform baselines on a real table: seeded deck, blind schedule, showdown with
side pots, and ICM settlement at the hand cap. `--hands` sets the cap (default
30), `--seed` makes a run exactly repeatable, and `-v` narrates every decision.
Raise semantics match the platform: the amount is your total contribution on
the current street. The simulator is a pure standard-library approximation of
the server engine for fast iteration, not the adjudicating engine itself.

`python icm.py 6000 3000 1500 1000` computes expected points for surviving
stacks, the same Independent Chip Model the platform uses to settle tables
that reach the hand cap.

Only run source you trust locally; all uploaded code is executed in Docker by
the platform, never by the web server.
