# Multi-game contracts (v1) — frozen before parallel implementation

Implements M0.2 of `plans/SOCIAL_GAMES_IMPLEMENTATION_PLAN.md`. These schemas
are the agreement between the registry, engines, API, worker and frontend.
Poker's existing `Agent.act(observation)` contract stays byte-for-byte
identical; new games use versioned JSON payloads inside the same transport.

## 1. Game registration

Registry lives in `backend/arena/games/registry.py`. Entries are trusted,
code-defined; user submissions can never supply engine code or pick
server-side modules.

```python
GameSpec(
    game_id="bluff",              # stable ID, lowercase
    rules_version=1,              # integer; immutable per published rules
    display_name="Bluff",
    variant_label="Stack Theory Bluff v1",
    seats=(4,),                   # legal seat counts
    tracks=("classic", "model"),  # allowed submission tracks
    adapter=BluffAdapter(),       # trusted, importable only from arena.games
)
```

`get_game(game_id, rules_version=None)` returns the spec or raises
`GameError` (mapped to HTTP 4xx). An omitted game parameter in any legacy API
call means `("poker", 1)`. An explicit unknown/unsupported ID is an error —
never a silent poker fallback.

Poker registers as `game_id="poker"`, `rules_version=1`, variant
"No-limit Texas Hold'em", seats 2–8, tracks classic+model, wrapping the
existing engine unchanged.

## 2. Card identity (shared convention)

Cards are unique strings `"{rank}{suit}"`: ranks `A 2 3 4 5 6 7 8 9 T J Q K`,
suits `c d h s` (e.g. `As`, `2h`, `Td`). One copy per (rank, suit) per deck;
IDs are therefore unique and can be used as set members directly.

## 3. Bluff observation schema (protocol 1)

Delivered to `Agent.act(observation)` of a bluff bot. Contains **no** hidden
state: no opponent hands, deck order, seed, face-down pile contents, or
challenge decisions that have not yet reached this seat.

```json
{
  "protocol": 1,
  "game": "bluff",
  "rules_version": 1,
  "seat": 2,
  "players": [{"seat": 0, "name": "Honest", "count": 4, "out": false},
               {"seat": 1, "name": "T1", "count": 6, "out": false},
               {"seat": 2, "name": "T2", "count": 3, "out": false},
               {"seat": 3, "name": "Random", "count": 0, "out": false}],
  "hand": ["Ac", "3d", "9s"],
  "required_rank": "A",
  "pile_size": 7,
  "turn": {"type": "play"},
  "history": [
    {"type": "play", "seat": 1, "rank": "A", "count": 2, "pile_size": 2},
    {"type": "resolution", "claimant": 1, "challenged_by": null,
     "revealed": null, "honest": null, "taken_by": null, "next_rank": "2"},
    {"type": "play", "seat": 2, "rank": "2", "count": 1, "pile_size": 1}
  ],
  "decision_number": 12,
  "decision_cap": 500
}
```

During a challenge sequence, `turn` is
`{"type": "challenge", "claimant": <seat>, "rank": "<claimed rank>",
  "count": <declared count>}` and `history` additionally contains the
`pass`/`challenge` events of deciders **before** this seat only. The
pending decision and future decisions are absent.

`history` event types (public):
- `play` — a face-down claim (rank + count only, never cards)
- `pass` / `challenge` — a decision inside the open sequence
- `resolution` — batch outcome. `revealed` (array of card IDs) is non-null
  **only** when `challenged_by` is non-null; an all-pass resolution keeps the
  batch hidden forever. `taken_by` is the seat that picked the pile up, or
  `null` when everyone passed. `next_rank` is the rank for the following
  batch. On a win, `winner_seats` is present on the terminal resolution.

## 4. Bluff action schema (protocol 1)

`Agent.act` returns one of:

```json
{"type": "play", "cards": ["Ac", "Ad"]}      // 1–4 owned card IDs, no duplicates
{"type": "challenge"}                          // during a challenge turn
{"type": "pass"}                               // during a challenge turn
```

Validation: play only during play turns; challenge/pass only during challenge
turns; cards must exist, be owned, and be distinct. Invalid actions, wrong
types, or timeouts record one **fault** for the acting seat and use a
deterministic fallback: play → the first card of the seat's hand in stable
sorted order; challenge decision → `pass`. `SandboxDown` is infrastructure:
the match aborts and is never scored.

## 5. Bluff match result schema

```json
{
  "points":      [1.0, 0.0, 0.0, 0.0],
  "winner_seats": [2],
  "terminal_reason": "win" | "cap",
  "faults":      [0, 0, 1, 0],
  "errors":      [null, null, "invalid play: unowned card 5h", null],
  "hands": 1,
  "matches": 1,
  "decisions": 47,
  "final_rank": "5",
  "log": [/* privileged audit: per-decision records incl. hidden state */],
  "frames": [/* public replay frames, section 6 */]
}
```

Scoring v1: a win scores 1, a loss 0; at the decision cap the current claim
and challenge sequence finish before scoring. With tied lowest
hand counts, 1 is split equally among tied winners. Event standing is the
average match score across the event's tables; match count and faults are
reported separately. Poker's eight-seat scoring is untouched.

## 6. Bluff replay schema (protocol 1)

```json
{"game": "bluff", "protocol": 1, "seats": 4,
 "names": ["T1", "Honest", "Random", "Counter"],
 "frames": [
   {"kind": "play", "seat": 0, "rank": "A", "count": 3, "pile_size": 3,
    "counts": [3, 4, 4, 4]},
   {"kind": "pass", "seat": 1, "pile_size": 3, "counts": [3, 3, 4, 4]},
   {"kind": "challenge", "seat": 2, "pile_size": 3, "counts": [3, 3, 4, 4]},
   {"kind": "resolution", "claimant": 0, "challenged_by": 2,
    "revealed": ["Ac", "2d", "5h"], "honest": false, "taken_by": 2,
    "pile_size": 0, "next_rank": "2", "counts": [0, 3, 9, 4]},
   {"kind": "end", "reason": "win", "winner_seats": [2], "counts": [0, 1, 0, 2]}
 ]}
```

`counts` = hand size per seat after the event. Frames never contain hidden
cards; only revealed challenged batches may appear. Poker replay frames are
unchanged. `replays.game_id` (new column) drives game-aware rendering; legacy
rows read as poker.

## 7. Submission compatibility

- `submissions` gains `game_id TEXT NOT NULL DEFAULT 'poker'` and
  `rules_version INTEGER NOT NULL DEFAULT 1` (additive ALTERs; legacy rows
  are poker).
- **Activation is scoped by (team, game, track).** Track is derived from the
  presence of a `model_submissions` row. All activation sites (manual POST,
  model validation, GitHub validation) deactivate only the same team + game +
  track, so activating a Bluff bot never deactivates a Poker bot.
- Manual source: `POST /api/submissions {name, source, game?}` — `game`
  defaults to `poker`; unknown games → 422. AST validation stays host-safe;
  sandbox smoke tests are game-specific.
- Model: `POST /api/models/submissions?game=bluff` (query, default poker).
- GitHub: `POST /api/github/connect` gains `game` (stored on
  `github_repositories`, default poker); webhook/sync payloads carry
  `game_id` and validation runs that game's smoke harness on the frozen
  commit.
- Round freeze joins submissions on the event's `game_id` + track; a team
  without a compatible active bot is excluded with the existing error
  semantics. Round payloads pin `game_id`, `rules_version`, event config,
  sandbox digest, seat plan and seed.

## 8. API surface (additive)

- `GET /api/games` → implemented games only:
  `{"games": [{"id", "name", "variant", "rules_version", "tracks", "seats"}]}`
- `GET /api/starter?game=`, `GET /api/starter/download?game=` — default poker.
- `POST /api/practice {submission_id?, hands?, game?, matches?}` — `hands`
  is poker-only; bluff uses `matches` (1–8). Bluff result:
  `{scores: [{name, points, faults, error}], replay_id, hands: <matches>,
    matches, game}`. Poker result shape unchanged.
- `POST /api/admin/events` gains `game`; stored `events.game_id`/`rules_version`
  (defaults poker); `variant` label comes from the registry.
- `GET /api/leaderboard?game=` — default `poker` (legacy shape preserved);
  bluff results are never summed into the default poker leaderboard.
- Event payloads gain `game`, `rules_version`; replay list/detail gain `game`.
- Unknown/unsupported game on any endpoint → `422` with a clear detail.

## 9. UNO prototype (protocol `uno`, rules_version 1) — TICKET-002

Familiar UNO as an exact, cited rules prototype — never labelled official; no
proprietary art. The builder owns a full rules doc (Mattel rules citation +
explicit deviation list) at `backend/arena/games/uno/RULES.md`, written before
code.

- **Deck (108):** per color r/y/g/b — one 0, two each 1–9, two each
  skip/reverse/draw-two (25 × 4) + 4 wild + 4 wild draw-four. Card IDs: color
  prefix + face (e.g. `r7`, `bskip`, `wwild4`) — exact scheme fixed in RULES.md.
- **Seats:** 2–4; 7 cards each; start-card flip rules per RULES.md.
- **Turn:** play a matching card, or draw (exact draw/play-through/pass rule
  fixed in RULES.md and never silently changed).
- **Action vocabulary (supervisor edges):** `{"type":"play","card":id}`,
  `{"type":"draw"}`, `{"type":"pass"}`, `{"type":"uno"}` (declaration),
  `{"type":"challenge"}` (wild-draw-four window only, exactly as RULES.md states).
- **Visibility table (the freeze):**
  - *public:* discard top, chosen color after a wild, all hand counts, turn
    direction, active seat, pending draw penalty, deck-reshuffle events, uno
    declarations, challenged-batch outcomes.
  - *private(seat):* own hand.
  - *hidden:* deck order, opponent hands.
- **Termination:** first empty hand (single-match mode); cap 500 decisions →
  fewest cards wins, ties share (platform convention).
- **Fault fallback:** deterministic — draw one card (pass if deck exhausted).
- **Scoring v1:** win 1 / loss 0 / ties share; standing = average match score.
- **Reuses `games/common/deck.py`** (TICKET-001) for the shuffled draw stack;
  color state is a public edge label, not hidden state.

## 10. Rummy 13-card (protocol `rummy`, rules_version 1) — TICKET-003

- **Deck (106):** two standard 52-card decks + 2 printed jokers (`XJ1`, `XJ2`);
  one random wild rank drawn at start and **public** (all suits of that rank act
  as jokers). Exact joker/wild semantics fixed in RULES.md (Mattel-style Indian
  Rummy citation + deviation list).
- **Seats:** 2–6; 13 cards each (deal from the shuffled 106 via
  `games/common/deck.py`); stock + single public discard stack.
- **Turn:** `{"type":"draw","from":"stock"|"discard"}` → optional
  `{"type":"declare","hand":[14 ids]}` (valid groups only: ≥2 sequences, ≥1
  pure, per RULES.md) → `{"type":"discard","card":id}`. Draw-then-declare
  replaces the discard step exactly as RULES.md states.
- **Visibility:** own hand private; stock order hidden; discard top public;
  wild rank public; opponent hands hidden; declared hands fully public at
  declaration.
- **Termination:** first valid declaration wins (single match); cap 500
  decisions → lowest deadwood points wins, ties share.
- **Fault fallback:** draw from stock; discard lowest by contract sort key.
- **Scoring v1:** win 1 / loss 0 / ties share; standing = average match score.

## 11. Hearts (protocol `hearts`, rules_version 1) — TICKET-004

- **Deck:** one standard 52, 4 seats, 13 each (`games/common/deck.py`).
- **Phases:** pass 3 cards (rotation by hand number: left → right → across →
  hold; single-match uses left) → 13 tricks. 2♣ leads first trick; follow suit
  mandatory; hearts cannot lead until broken; Q♠ = 13 points, hearts 1 each;
  shooting the moon = shooter 0, others +26 — exactly per RULES.md (Hoyle
  citation + deviation list).
- **Actions:** `{"type":"pass","cards":[3 ids]}` during the pass phase;
  `{"type":"play","card":id}` during tricks.
- **Visibility:** hands private; passed cards revealed to the receiver only;
  current-trick plays public; completed tricks fully public.
- **Termination:** 13 tricks = structurally bounded path (safety cap 500
  anyway); winner = fewest points, ties share.
- **Fault fallback:** pass the 3 lowest; play lowest legal card.

## 12. Hexchange v1 (protocol `hexchange`, rules_version 1) — TICKET-005

Social hex-island trading game **inspired by** the classic trading board game —
never named "Catan" in the registry/UI; no proprietary art. RULES.md cites the
inspiration and lists every deviation.

- **Board (public):** 19 hexes (4 forest, 4 pasture, 4 wheat, 3 brick, 3 ore,
  1 desert) in the classic island graph; seeded number tokens 2–12 (no 7);
  54 roads / 20 settlements / 16 cities per supply. Resource tokens are opaque
  per-seat strings (own engine module; does NOT use games/common/deck.py).
- **Dev deck (hidden):** 14 knight, 5 VP, 2 monopoly, 2 road-building,
  2 year-of-plenty (25 cards).
- **Turn:** dice roll (chance, seeded; 7 = robber: move + steal 1 random card
  from an adjacent seat holding >7 — steal target public, stolen card hidden)
  → main phase actions → `{"type":"end_turn"}`.
- **Action vocabulary:** `{"type":"build_road"|"build_settlement"|"build_city", ...}`,
  `{"type":"buy_dev"}`, `{"type":"play_dev", ...}`,
  **trade overlay:** `{"type":"offer","give":{...},"want":{...}}` → other seats
  respond `accept` | `reject` | `counter{give,want}`; first accept executes;
  max 3 offers per turn (finite negotiation edges); bank trades 4:1.
- **Visibility:** board, all buildings, resource *counts*, all trade offers,
  robber position public; resource card identities, dev deck, and dev cards
  private/hidden.
- **Termination:** first 10 VP (settlement 1, city 2, VP card 1); **deviations
  declared in RULES.md: no longest-road/largest-army in v1**; cap 500 → most
  VP wins, ties share.
- **Fault fallback:** `end_turn`; trade responses fall back to `reject`.

## 13. Invariants preserved

Lease fencing, atomic round publication, `SandboxDown` = infrastructure
failure, score-chain append-only auditing, hand-log persistence (per match
for bluff), privacy of unrevealed state in every public surface (observations,
frames, job results, errors, listings), bounded message sizes, and no
execution of submitted code on the host.
