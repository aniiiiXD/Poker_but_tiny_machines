# UNO starter kit (Stack Theory UNO v1 — rules prototype)

Familiar UNO as an exact, source-cited rules prototype — not an official
Mattel product. On your turn you play a card matching the discard top by
color or face (wilds always fit and choose the next color), or draw one card.
Action cards skip, reverse, and penalize; the first empty hand wins.

## Rules (Stack Theory UNO v1)

- 2–4 seats, the classic 108-card deck, 7 cards each, one hand per match.
  The authoritative rules document is `backend/arena/games/uno/RULES.md`,
  which cites the official Mattel rules and lists every deviation.
- Card IDs are `{color}{face}{copy}`: colors r/y/g/b (+ w for wilds), faces
  0–9 / skip / reverse / draw2 / wild / wild4, and a copy letter a–d, e.g.
  `r7a`, `bskipa`, `wwild4d`.
- On a normal turn: `{"type": "play", "card": id}` (wilds must add
  `"color"` in r/y/g/b) or `{"type": "draw"}`. Passing without drawing is a
  fault.
- After drawing, if the drawn card is playable you may play **only that
  card** (`post_draw` turn) or `{"type": "pass"}`.
- Skip / reverse / draw two act on the next player in the current direction;
  in two-seat play a reverse acts as a skip. Draw penalties arrive as
  `penalty` turns where `{"type": "draw"}` is the only legal action.
- A wild draw four opens a one-seat challenge window for its victim: guilty
  (the player held a card of the previous color) → they draw 4 and you play;
  innocent → you draw 6 and are skipped.
- Playing down to one card opens a `uno` declaration window: declare
  (`{"type": "uno"}`) or decline and eat the 2-card catch penalty.
- No stacking. First empty hand wins (a last-card wild draw four is judged by
  its challenge window first). After 500 decisions the player with the fewest
  cards wins; ties share the point. Invalid actions count as faults and fall
  back to a deterministic legal move.

## What your bot sees

Only public information plus your own hand: the discard top, the active
color, direction, seat counts and UNO flags, the pending draw penalty, and
the current decision window. Never the seed, the draw-stack order, or
opponent hands.

## Files

- `agent.py` — a documented starter you can submit as-is, then improve.
- Edit locally, then upload in the Workshop (choose the UNO game) or push
  `agent.py` to a connected GitHub repository.

## Strategy ideas

- Choose wild colors you hold most of; hoarding one color also limits what
  opponents can match.
- Action cards are worth more when the next player is down to one or two
  cards — and a wild draw four played illegally can be challenged for a
  4-card swing.
- Track who has declared UNO (public flag) and hold a skip or draw two to
  catch them before they empty their hand.
- Declaring UNO is free; declining costs two cards. Never decline by accident.
