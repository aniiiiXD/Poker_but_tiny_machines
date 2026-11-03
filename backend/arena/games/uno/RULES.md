# Stack Theory UNO v1 — rules prototype (rules_version 1)

A familiar-rules UNO prototype for Stack Theory. UNO® is a trademark of
Mattel, Inc. This document, the engine it describes, and any UI built on them
are **not official**, carry no Mattel branding, art, or card faces, and must be
labelled a prototype. Trademark review is a human gate before any public
branding.

This document was written **before** `engine.py` and is binding on it: the
engine implements exactly what is written here, and any deviation discovered
while coding had to be added to Section 2, never made silently.

## 1. Source of rules

The basis is Mattel's published instruction sheet for classic UNO ("UNO® Card
Game Instructions", Mattel Play, instructions.mattel.com — the classic
four-color, 108-card edition). Every mechanic below follows that sheet except
where Section 2 lists an explicit deviation. Editions of the sheet differ on a
few points (noted inline); where they do, this document picks one behavior and
states it as normative for this prototype.

## 2. Deviations from the official rules (complete list)

- **D1 — Single-match mode.** Official UNO is a multi-hand race to 500 points
  with card-point scoring. This prototype plays exactly **one hand per
  match**; the first empty hand wins. Card point values (numbers, 20, 50) are
  never used anywhere.
- **D2 — Decision cap of 500.** Official rules have no clock. At 500 decisions
  any in-progress sequence (a draw, penalty serve, UNO declaration, or
  draw-four challenge window) finishes, then the player with the **fewest
  cards** wins; ties share the point (platform convention, mirrors Bluff).
- **D3 — Seeded deterministic deck.** Official shuffling is physical. Here the
  108-card deck is shuffled once by the shared `games/common/deck.py` engine
  from a match seed, and reshuffles reuse the same seeded stream, so a match
  replays exactly from (bots, seed).
- **D4 — Bot fault fallback.** An invalid, late, or crashed bot decision is
  recorded as a fault and replaced by a deterministic fallback: on a play or
  penalty turn the fallback is **draw one** (a draw that cannot serve any card
  simply ends the turn); on a post-draw turn it is **pass**; on a UNO
  declaration window it is **declare**; on a challenge window it is **pass**.
- **D5 — Card IDs carry a copy letter.** Official decks contain two
  indistinguishable copies of most faces; the suggested bare IDs (`r7`,
  `bskip`) would collide. Every ID therefore ends in a copy letter (a–d), see
  Section 3. This is a machine-identity change only; the printed deck is
  unchanged.
- **D6 — UNO declaration is an explicit, engine-enforced action.** Officially
  players yell "UNO" and opponents catch them before the next player begins.
  Here, when a play leaves a player exactly one card, that same player
  immediately receives a declaration decision: `{"type":"uno"}` declares
  (public event), `{"type":"pass"}` declines. Declining — or faulting on the
  window — costs the official **2-card catch penalty**, served immediately.
  There is no opponent catch race.
- **D7 — Wild Draw Four challenge semantics are pinned.** Editions differ on
  the failed-challenge draw and on turn handling. Normative here: only the
  penalized (next) player may challenge, in exactly one decision window.
  **Guilty** (the wild-draw-four player held a card of the color in effect
  before the wild): the wild-draw-four player draws 4 cards and the challenger
  takes their normal turn. **Innocent:** the challenger's penalty grows from 4
  to **6** (4 + 2) and they are skipped. Officially the challenged hand is
  shown to the challenger; here only the guilty/innocent **outcome** becomes
  public — the frozen visibility table has no revealed-hands field.
- **D8 — Wild-draw-four legality is not enforced by the engine.** Officially
  the card may only be played without a matching-color card in hand. Here any
  wild-draw-four play is accepted and the challenge window (D7) is the sole
  remedy, matching the official "you may play it and risk a challenge"
  reading.
- **D9 — Start-card wilds are re-flipped.** Officially a wild start card lets
  the first player choose a color before playing. The frozen action vocabulary
  has no pre-play color choice, so a flipped **wild or wild draw four** is
  returned to the **bottom** of the draw stack and another card is flipped
  (extending the official wild-draw-four re-flip to plain wilds).
- **D10 — Penalty draws are explicit turns.** Officially the penalized player
  draws mechanically. Here a pending penalty is a real decision turn
  (`{"type":"penalty"}` requiring `{"type":"draw"}`), which keeps the frozen
  public *pending draw penalty* observation field live. Faulting on it falls
  back to the draw (D4).
- **D11 — Draw-stack refill when short.** Officially the discard pile is
  reshuffled when the draw stack runs out. Here, whenever a draw needs more
  cards than the stack holds, the discard pile **minus its top card** is
  returned to the stack (mixed with any remaining draw cards) and reshuffled
  once per draw event. If cards are still unavailable, the draw serves fewer —
  possibly zero — cards and the turn proceeds.
- **D12 — Returned cards go to the bottom.** Officially re-flipped and
  reshuffled cards go "back in the middle"; the prototype uses the bottom of
  the draw stack, which is deterministic.
- **D13 — Winning last cards.** A **non-wild** last card wins immediately and
  its targeting effect (skip / draw two on the next player) is not applied —
  the match is over. A last-card **wild draw four** still opens the challenge
  window, because the outcome can change the winner; if the match is decided
  by that window, any remaining penalty draw is moot and is not served.
- **D14 — Deterministic dealer.** There is no dealer cut. Seat 0 is the
  nominal dealer; play starts clockwise at seat 1 ("left of the dealer"), and
  start-card effects are applied relative to that.

Non-deviation clarifications: the classic sheet's home variants (stacking
Draw Twos, 7-0, jump-in, Progressive UNO) were never official and are not
adopted; drawing voluntarily while holding a playable card is legal (official);
declining to play a playable drawn card ends the turn (the sheet is silent;
the pass action covers it).

## 3. Card identity (ID scheme — frozen)

An ID is `{color}{face}{copy}`:

- color letter: `r` red, `y` yellow, `g` green, `b` blue, `w` wild;
- face: `0`–`9`, `skip`, `reverse`, `draw2`, and for wilds `wild`, `wild4`;
- copy letter: `a`–`d`, distinguishing printed copies of the same face.

Examples: `r0a`, `r7a`, `r7b`, `bskipa`, `bskipb`, `gdraw2b`, `wwilda`,
`wwild4d`. Copies are interchangeable; the letter exists only to make IDs
unique set members (D5). Parsing is uniform: `card[0]` is the color,
`card[1:-1]` the face, `card[-1]` the copy. Hands are sorted by (color order
r,y,g,b then w; face order 0–9, skip, reverse, draw2, wild, wild4; copy
letter) — wilds tidy last.

## 4. Deck composition (108 cards)

Per color r/y/g/b: one `0`, two each of `1`–`9`, two each of `skip`,
`reverse`, `draw2` — 25 cards × 4 colors = 100. Plus 4 wild (`wwild`a–d) and
4 wild draw four (`wwild4`a–d) = **108**.

## 5. Seats, deal, and the start-card flip

2–4 seats. Each seat is dealt 7 cards, one card at a time in seat order
(round-robin from the shuffled stack). The top card of the draw stack is
flipped to start the discard pile:

- **number** — sets the active color; seat 1 plays first.
- **skip** — seat 1 is skipped; seat 2 plays first.
- **reverse** — direction becomes counterclockwise; the seat right of the
  dealer (seat n−1) plays first. With two players this acts as a skip
  (Section 13).
- **draw two** — seat 1 has a pending penalty of 2 (they draw two and are
  skipped, D10).
- **wild / wild draw four** — returned to the bottom of the draw stack and
  another card is flipped (D9). The final start card is never a wild.

The start card, the active color, and the direction are public.

## 6. Turn structure and action vocabulary

Play proceeds in the current direction. A seat's normal turn (`play`) allows:

- `{"type":"play","card":id}` — play a legal card (Section 7). A wild must
  also carry `"color"` (Section 9).
- `{"type":"draw"}` — draw exactly one card (Section 10).

Passing without drawing is **not** legal on a normal turn (official: you must
draw if you cannot play). Follow-up decision windows:

- `{"type":"post_draw","card":id}` — the drawn card was playable; play exactly
  that card or `{"type":"pass"}`.
- `{"type":"penalty","draw":k}` — the seat owes k penalty cards; the only
  legal action is `{"type":"draw"}`. The engine serves exactly k cards (fewer
  if the stack cannot supply, D11). Serving ends the turn: the penalized
  player is skipped and play moves on.
- `{"type":"uno"}` — declaration window after playing down to one card
  (Section 11).
- `{"type":"challenge", ...}` — wild-draw-four window (Section 12).

## 7. Matching rules

A card is playable on the discard top when it is a wild, its **color** equals
the active color, or its **face** equals the top card's face. The active color
is the chosen color after any wild, otherwise the top card's color. A wild
top carries no face, so only color matches apply against it. Number cards
match only by color or identical face; symbols (skip/reverse/draw2) match by
color or identical symbol across colors.

## 8. Action cards

- **Skip** — the next player in the current direction loses their turn; the
  player before them plays next.
- **Reverse** — direction flips; the previous player plays next (in two-player
  play it acts as a Skip, Section 13).
- **Draw two** — the next player has a pending penalty of 2 and is skipped.
  No stacking.
- **Wild** — the player chooses the new color (Section 9).
- **Wild draw four** — the player chooses the new color and the next player
  has a pending penalty of 4 and is skipped, subject to the challenge window
  (Section 12). Legality is challenge-only (D8).

All action-card effects are applied in full even when the played card is the
player's second-to-last card; the UNO declaration window (Section 11) is
resolved before any effect of the play.

## 9. Wild color choice

Playing a wild or wild draw four **requires** a color field:
`{"type":"play","card":"wwilda","color":"g"}` with color ∈ r/y/g/b. The chosen
color becomes the public active color immediately. A wild play without a valid
color is a fault (fallback: draw one, D4). A color field on a non-wild play is
ignored.

## 10. Drawing, play-through, and pass

Drawing is always legal on a normal turn, even holding playable cards. A
voluntary draw takes exactly one card. If the drawn card is playable, the seat
gets a `post_draw` window and may play **only the drawn card** (never another
card from hand) or pass. If the drawn card is not playable — or nothing could
be drawn (D11) — the turn ends with no decision. Passing is legal only in the
post-draw window.

## 11. UNO declaration and penalty

When a play leaves a player with exactly **one** card, that player immediately
receives a `{"type":"uno"}` decision: `{"type":"uno"}` declares (a public
event), `{"type":"pass"}` declines. Declining or faulting costs the official
2-card catch penalty, served immediately by the engine (D6). The public
`uno` flag on a player is true exactly while that seat has declared on their
current one-card hand; it clears as soon as the hand size changes. A player
who empties their hand wins outright — no declaration is requested. The
declaration window is resolved before the challenge window of the same play.

## 12. Wild Draw Four challenge

After a wild draw four is played, and after any UNO declaration window, the
penalized player receives exactly one `{"type":"challenge"}` decision (the
`turn` object carries the wild card, its chosen color, and the 4-card
penalty):

- `{"type":"pass"}` — no challenge; the 4-card penalty stands.
- `{"type":"challenge"}` — the play is judged against the color in effect
  **before** the wild was played. Guilty → the wild-draw-four player draws 4
  cards and the challenger takes their normal turn. Innocent → the
  challenger's penalty becomes 6 (4 + 2) and they are skipped (D7).

A last-card wild draw four is judged the same way; with an empty hand it is
always innocent, and the match ends after the window either way (D13).

## 13. Two-player behavior

With two seats: **reverse acts as skip** — the same player plays again and the
direction is unchanged; skip, draw two, and wild draw four penalize the
opponent, who is skipped, so the penalizing player plays again.

## 14. Deck exhaustion and reshuffle

When a draw needs more cards than the draw stack holds, the discard pile minus
its top card is returned to the stack and reshuffled with the seeded stream
(D11, D12); the event is public. If cards are still unavailable the draw
serves what remains — possibly nothing — and the turn proceeds. The top card
of the discard pile never re-enters the stack.

## 15. Termination and the decision cap

The match ends when a player's hand becomes empty **and** no challenge window
can refill it (a last-card wild draw four is not a win until its window
resolves). Otherwise the match ends at the 500-decision cap (D2): pending
sequences finish, then fewest cards wins and ties share the point. The cap is
checked before each fresh normal turn; one pending chain may push the decision
count slightly past it, mirroring the Bluff engine.

## 16. Scoring

Win = 1, loss = 0; tied fewest-card winners share 1 equally. Event standing is
the average match score across the event's tables. No card-point scoring
exists in this prototype (D1).

## 17. Machine contract

**Observation (per decision, per seat)** — the frozen §9 visibility table:
private(seat) own hand; public discard top, chosen color, all hand counts,
uno flags, direction, active seat, pending draw penalty; hidden deck order and
opponent hands (never present anywhere). Exact key set:

```
protocol, game, rules_version, seat, players, hand, discard_top,
active_color, direction, active_seat, pending_draw, turn,
decision_number, decision_cap
```

`players` entries are `{seat, name, count, uno}`; `direction` is `"cw"` or
`"ccw"`; `pending_draw` is the penalty pending on the seat about to act (0
otherwise). There is no history field — the frozen table is exhaustive.

**Fault fallbacks (D4)** — play turn → draw one; post-draw → pass; penalty →
the penalty draw; UNO window → declare; challenge window → pass; a draw that
cannot serve ends the turn. `SandboxDown` is infrastructure: the match aborts
and is never scored.

**Replay** — `{"game":"uno","protocol":1,"names":[...],"frames":[...]}`.
Public frame kinds: `start` (card, color, direction, active seat), `play`
(seat, card, chosen color for wilds), `draw` (seat, count — **never** card
IDs), `pass`, `penalty` (seat, count), `skip` (skipped seat), `reverse`
(direction), `uno`, `uno_penalty` (seat, count), `challenge` (decision),
`challenge_result` (seat, player, guilty), `reshuffle` (count), `end`
(reason, winner seats). Every frame carries public `counts` after the event.
Frames never contain drawn cards, hands, deck order, or the seed.

**Result** — `{points, winner_seats, terminal_reason, faults, errors, hands,
matches, decisions, final_action, names, log, frames}` where `hands`/`matches`
are 1 (single match), `final_action` is the last completed action in public
summary form, `log` is the privileged audit (includes drawn card IDs, final
hands, discard pile, draw-stack depth, re-flip counts — never exported
publicly), and `frames` is the replay wrapper above.
