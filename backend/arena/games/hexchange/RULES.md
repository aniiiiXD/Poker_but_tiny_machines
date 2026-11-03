# Hexchange v1 — Rules

*Stack Theory arena game · protocol `hexchange` · rules version 1*

Hexchange is a social hex-island trading game for 3–4 seats, **inspired by the
classic hex-island trading board game designed by Klaus Teuber, first published
in 1995**. It is an original, independent implementation for the Stack Theory
arena: the classic game's name never appears in the registry, UI, or any
user-facing string, and no proprietary art is used.

This document is the complete authority for Hexchange v1. Every deviation from
the classic game is listed explicitly in **§14 Deviations**; anything not listed
there follows the familiar shape of the classic game as described here.

## 1. Seats and goal

- 3 or 4 seats. Seat 0 takes the first turn; play proceeds in ascending seat
  order, wrapping around.
- Each seat tries to reach **10 victory points (VP)** first. VP come from
  buildings (settlement 1, city 2) and secret victory-point development cards
  (1 each). There are no other VP sources in v1.

## 2. The island

- The island is always the **19-hex graph**: pointy-top hexes in rows of
  3–4–5–4–3. It has **54 buildable vertices** (settlement/city spots) and
  **72 road edges**.
- Terrain distribution (frozen): **4 forest, 4 pasture, 4 wheat, 3 brick,
  3 ore, 1 desert**. Each non-desert terrain produces its own resource token
  named after the terrain: `forest`, `pasture`, `wheat`, `brick`, `ore`.
  The desert produces nothing.
- **Number tokens** `2–12` without `7` — exactly `2, 3, 3, 4, 4, 5, 5, 6, 6,
  8, 8, 9, 9, 10, 10, 11, 11, 12` (18 tokens) — are shuffled onto the 18
  non-desert hexes by the match seed. The classic "no 6/8 on adjacent hexes"
  refinement is **not** enforced (§14).
- Hex, vertex, and edge ids are integers fixed by geometry (hexes in row
  order, vertices and edges in sorted spatial order). **The seed never
  changes the ids** — it only assigns terrain and numbers.
- The **robber** starts on the desert hex. A hex occupied by the robber
  produces nothing.

## 3. Setup

Before the first turn, each seat places **two settlements and two roads**, in
snake order: seats `0, 1, …, n-1` place their first settlement + road, then
`n-1, …, 1, 0` place their second settlement + road.

- Setup placements are **free** (no resource cost) and do not count against
  the per-turn build limits; they do consume the table supply (§7).
- A setup settlement needs an empty vertex that respects the distance rule
  (§6). A setup road must touch the settlement just placed this round.
- The **second** settlement pays out immediately: its owner gains one resource
  token from each adjacent non-desert hex. The first settlement pays nothing.

## 4. Turn structure

A turn runs, in order:

1. **Dice roll** (chance, engine-driven, seeded): two six-sided dice; their
   sum drives production (§5). The roll is public.
2. **Production** — or, on a sum of **7**, the robber (§6).
3. **Main phase**: the active seat submits actions in any order, any number of
   them, until it submits `{"type": "end_turn"}`.
4. The turn passes to the next seat.

Main-phase actions (all public):

| Action | Payload |
|---|---|
| Build road | `{"type": "build_road", "edge": <edge id>}` |
| Build settlement | `{"type": "build_settlement", "vertex": <vertex id>}` |
| Build city | `{"type": "build_city", "vertex": <vertex id>}` |
| Buy development card | `{"type": "buy_dev"}` |
| Play development card | `{"type": "play_dev", "card": ..., ...}` (§9) |
| Open a trade offer | `{"type": "offer", "give": {...}, "want": {...}}` (§8) |
| Bank trade | `{"type": "bank_trade", "give": {...}, "want": {...}}` (§8) |
| End turn | `{"type": "end_turn"}` |

When a 7 is rolled (or a knight is played), the active seat's next decision is
instead the robber move `{"type": "move_robber", "hex": <hex id>,
"steal": <seat or null>}` (§6), after which the main phase continues.

## 5. Production

- Both dice are summed. Every non-desert hex whose number token equals the sum
  **and** that is not robber-blocked produces.
- Each **settlement** adjacent to a producing hex yields 1 token; each **city**
  yields 2. Tokens go to the owning seat's hand.
- The roll, the producing hexes, and the per-seat **totals** gained are public.
  **Which token types each seat received is private** (only visible to the
  receiver through its own hand).

## 6. The robber

On a roll of **7** there is no production. The active seat must move the
robber and may steal:

- `{"type": "move_robber", "hex": H, "steal": S}` — the robber moves to hex
  `H`, which must be **different from the hex it currently occupies**.
- After the move, the active seat may steal **1 random resource token** from
  one seat `S` that (a) is **not** the mover, (b) has a settlement or city on a
  vertex of hex `H`, and (c) holds **more than 7 resource tokens**. `steal`
  may be `null` to steal nothing. Choosing an ineligible target is an invalid
  action.
- The steal target is public; the **stolen token's identity is never
  published**. The victim can infer it from their own hand, the thief sees it
  land in their own hand, and no other seat ever learns it. The draw is seeded
  by the match RNG.

## 7. Buildings, supply, and costs

Placement legality (graph rules):

- **Settlement**: on an empty vertex that is **not adjacent** to any existing
  settlement or city (the distance rule: buildings are always ≥ 2 vertices
  apart), and — outside setup — connected to at least one of the seat's roads.
- **City**: only on the seat's **own settlement** (which becomes a city).
- **Road**: on an empty edge that touches the seat's network — at least one
  endpoint of the edge must hold the seat's building, or be an empty vertex
  with one of the seat's roads. A road can never connect *through* another
  seat's settlement.

Supply (frozen): the table shares **54 roads, 20 settlements, 16 cities**. In
addition the classic per-seat piece limits apply: at most **15 roads,
5 settlements, 4 cities** per seat at any moment. Upgrading a settlement to a
city returns the settlement piece to its owner's stock and to the table
supply.

Cost matrix (frozen):

| Build | Cost |
|---|---|
| Road | 1 brick + 1 forest |
| Settlement | 1 brick + 1 forest + 1 pasture + 1 wheat |
| City | 2 wheat + 3 ore |
| Development card | 1 ore + 1 pasture + 1 wheat |

## 8. Trading

**Bank trades (4:1).** The active seat may trade with the bank at any time:
`{"type": "bank_trade", "give": {"<resource>": 4}, "want": {"<resource>": 1}}`
— exactly 4 tokens of one type for exactly 1 token of a different type. The
bank's supply is unlimited. There are no harbors or port rates in v1 (§14).

**The trade overlay.** Player-to-player trade is a structured, finite
negotiation edge — no free text, ever.

1. The active seat opens an offer:
   `{"type": "offer", "give": {...}, "want": {...}}` — the offering seat gives
   `give` and wants `want`. Both maps are `{resource: positive count}`.
2. The offer is broadcast; every **other** seat responds **in seat order,
   starting after the offering seat**, with exactly one of:
   - `{"type": "accept"}` — the trade **executes immediately** (first accept
     wins): the offering seat pays `give` and receives `want`; the accepting
     seat pays `want` and receives `give`. The offer round ends.
   - `{"type": "reject"}` — the next seat in order responds.
   - `{"type": "counter", "give": {...}, "want": {...}}` — from the countering
     seat's perspective (they give `give`, want `want`). The counter
     **replaces** the active offer, and the response round restarts with the
     seats after the countering seat. Each seat responds at most once per
     active offer, and a counter author never responds to their own counter.
3. When every responder has rejected — or the final offer's responders run out
   — the offer expires and control returns to the active seat's main phase.
4. **Budget: at most 3 offers per turn**, counting the active seat's initial
   offer and every counter. An offer or counter beyond the budget is an
   invalid action (§12).
5. **Affordability:** the author must be able to pay `give` when authoring. An
   accepting seat must be able to pay `want` at the moment of acceptance; an
   accept they cannot pay is an invalid action (fault + treated as reject).
6. All offer, counter, accept, and reject events are public, including the
   resource maps. Resource **totals** per seat are public, but the identity
   composition of a seat's hand is not.

## 9. Development cards

The dev deck holds **25 cards, hidden**: 14 knight, 5 victory-point,
2 monopoly, 2 road-building, 2 year-of-plenty, shuffled by the match seed.
`buy_dev` draws the top card into the buyer's secret hand.

- **One development card may be played per turn**, and **never a card bought
  on the same turn**.
- **Knight** — `{"type": "play_dev", "card": "knight"}`: move the robber as in
  §6 (the move may then be followed by the steal). Unlike a 7, production was
  not skipped. Knights have no bonus effect in v1 (§14).
- **Monopoly** — `{"type": "play_dev", "card": "monopoly", "resource": R}`:
  the active seat takes **all** tokens of type `R` from every other seat. The
  chosen type and per-seat totals taken are public; the cards themselves were
  never public anyway (only totals change).
- **Road-building** — `{"type": "play_dev", "card": "road_building"}`: the
  active seat immediately places **2 free roads** (normal placement legality,
  no cost). An unplaceable free road is forfeited.
- **Year of plenty** — `{"type": "play_dev", "card": "year_of_plenty",
  "resources": [R1, R2]}`: gain the two named tokens from the bank (they may
  repeat). The choices are public.
- **Victory point** — never played. It counts toward its owner's VP
  immediately and **secretly**; it can complete the 10-VP win, revealed only
  at the end of the match.

## 10. Winning

- The first seat to hold **10 or more VP** (buildings + secret VP cards)
  wins immediately; the match ends at that moment.
- **Decision cap**: an arena match allows at most 500 agent decisions. When
  the cap is reached the match ends immediately (`terminal_reason: "cap"`);
  the seat(s) with the **most VP** win and **ties share** the match point.

## 11. Visibility table (the freeze)

| Public | Private (own seat only) | Hidden |
|---|---|---|
| board (hexes, terrain, numbers, vertices, edges), all buildings, all roads, robber position, dice rolls, producing hexes, per-seat resource **totals**, public VP (buildings only), every trade offer/response with its resource maps, every dev card **played** (with its declared effect), dev purchase events (no type) | own resource tokens **by type**, own development cards **by type** | dev deck order and remaining composition, opponents' resource identities, opponents' dev cards (existence and counts), the stolen token's identity, secret VP cards until the match ends |

## 12. Faults, fallbacks, and bounds

- Every agent decision is validated. An invalid, illegal, malformed, crashing,
  or timed-out decision records **one fault** for the seat and applies a
  deterministic fallback:
  - main-phase decision → `{"type": "end_turn"}`;
  - trade response → `{"type": "reject"}`;
  - robber move → the first legal hex in id order, stealing the first eligible
    target in seat order (or nobody);
  - setup placement → the first legal vertex/edge in id order;
  - free road → the first legal edge in id order (forfeited if none).
- `SandboxDown` (infrastructure failure) aborts the match and is never scored
  as faults.
- Observations carry the **most recent 100 public events** (bounded transport);
  the full event stream lives in the privileged match log only.
- The board and every decision path are finite: the decision cap guarantees
  termination.

## 13. Scoring

`points` reports final VP per seat. `match_points` awards 1 point shared
equally among the winner seat(s) ( outright win or cap-time leaders). A seat's
standing in an event is the average of its match points.

## 14. Deviations from the classic game (complete list)

1. **No special VP bonuses.** The classic longest-road (+2 VP) and
   largest-army (+2 VP) bonus cards are not implemented in v1.
2. **Fixed island.** Every match uses the same 19-hex island graph (§2),
   generated deterministically from the match seed. No other map sizes.
3. **3–4 seats.** The classic 2-player and 5–6-player variants are out of
   scope.
4. **Single match to 10 VP.** One continuous match per arena pairing; no
   multi-game series.
5. **Seeded number placement.** Number tokens are shuffled onto the island by
   the match seed; the classic rule that 6 and 8 never sit on adjacent hexes
   is **not** enforced.
6. **No harbors.** Port trades (3:1 and 2:1) do not exist; every seat trades
   with the bank at a flat 4:1.
7. **Unlimited bank.** The bank never runs out of resource tokens.
8. **No discard on a 7.** Seats holding more than 7 tokens when a 7 is rolled
   do **not** discard half their hand.
9. **Steal threshold.** The robber may only steal from a seat holding **more
   than 7 tokens** (the classic game allows stealing from any adjacent seat).
10. **The robber must move.** The robber always moves to a hex different from
    the one it occupies; it can never stay.
11. **Shared building supply.** The table shares one supply of 54 roads,
    20 settlements, and 16 cities (the classic game ships 15/5/4 pieces per
    player); the classic per-seat limits are enforced on top of it.
12. **Fixed first seat.** Seat 0 always takes the first turn; the classic
    start-player dice roll is not played.
13. **Token names.** Resource tokens are named after their terrain
    (`forest`, `pasture`, `wheat`, `brick`, `ore`) rather than the classic
    lumber/wool/grain names.
14. **Bounded negotiation.** At most 3 trade offers may be opened per turn,
    responses are restricted to the structured `accept`/`reject`/`counter`
    vocabulary, and there is no free-text chat. (This is the platform's
    negotiation overlay rather than a classic rule.)
15. **Bounded history.** Observations carry the most recent 100 public events
    rather than the full history.
