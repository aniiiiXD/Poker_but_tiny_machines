# Stack Theory Hearts v1 — rules (rules_version 1, protocol `hearts`)

The authoritative rules text for `backend/arena/games/hearts/` (TICKET-004).
Frozen before implementation, per `GAMES_CONTRACT.md` §11 and the build
machine's "contract before tickets" rule. Every deviation from the cited
source is listed explicitly in the deviations section; nothing is changed
silently.

## Source

Classic four-player Hearts as described in *Hoyle's Rules of Games*
(Morehead, Mott-Smith & Frey — the "Hearts" chapter): the standard American
trick-avoidance game in which the 2♣ opens, players must follow suit, hearts
cannot lead until broken, the Q♠ costs 13, each heart costs 1, and taking
every penalty card is "shooting the moon".

This is a faithful cited prototype for a competitive bot arena. It is never
presented as an official Hoyle product, and no proprietary artwork is used.

## Table and deck

- Exactly 4 seats, numbered 0–3 clockwise. One standard 52-card deck, no
  jokers. Card IDs follow the platform convention (`GAMES_CONTRACT.md` §2):
  `"{rank}{suit}"`, ranks `A 2 3 4 5 6 7 8 9 T J Q K`, suits `c d h s`.
- The deal is 13 cards to each of the 4 seats (13 × 4), dealt round-robin
  from one seeded shuffle performed by the shared deck engine
  (`arena/games/common/deck.py`). The deck is never cut and no card can be
  exposed (see deviation D4).
- **Card strength** for winning tricks and for every "low/high" choice in
  this document: **2 is lowest, then 3 … 10, J, Q, K, ace highest** — the
  natural Hearts order, *not* the contract's `A…K` tidy-hand sort, which is
  only used to keep stored hands in a stable display order.
- Suit tie-break: clubs < diamonds < hearts < spades.

## The pass

- Before the first trick, each seat passes exactly 3 cards from their hand.
- Single-match mode always uses the **left** pass: seat *i* passes to seat
  *(i + 1) % 4*. (The classic multi-hand rotation — left, right, across,
  hold — is deviation D2.)
- All four seats submit their 3 cards **simultaneously**: every seat chooses
  from its original 13-card hand without seeing any incoming cards; the
  submissions are collected first and only then revealed, each to its
  receiver alone. A passed card is private to the receiver from then on and
  is simply part of their hand.

## The tricks

1. The seat holding the **2♣** after the pass **must lead it** to the first
   trick. Nothing else may be led to trick one.
2. Play proceeds clockwise from the leader; each seat plays exactly one card
   to the trick.
3. **Follow suit is mandatory**: a seat holding a card of the suit led must
   play one. Only a card of the led suit can win the trick.
4. A seat void in the led suit may play any card, penalty cards included
   (see deviation D3 for the first-trick nuance).
5. **Hearts cannot be led until hearts are broken.** Hearts are broken the
   moment any heart is played to a trick (normally as a discard). The only
   exception: a leader whose hand is *all hearts* may lead a heart. The Q♠
   is a spade — leading spades, including the Q♠ itself, needs no broken
   hearts and does not break them (clarification C1).
6. The **highest card of the led suit wins** the trick and collects it. The
   winner leads the next trick.
7. Completed tricks become part of the public record; nothing is hidden back.

## Scoring

- Each heart taken is **1 penalty point**; the **Q♠ is 13 penalty points**.
  26 penalty points are in play every hand.
- **Shooting the moon**: a seat that takes all 26 penalty points scores **0**,
  and every other seat scores **26** (deviation D5 fixes the variant).
- Single-match mode plays **exactly one hand of 13 tricks**. The game ends
  when the thirteenth trick is complete; there is no accumulation across
  hands (deviation D1). The platform decision cap (500) is a safety net the
  rules path can never reach (4 passes + 52 plays = 56 decisions).
- **Match scoring (platform convention):** the seat(s) with the fewest
  penalty points win; tied winners share one match point equally
  (`match_points`). Raw penalty `points` are reported per seat as-is.

## Agent interface (owned by `GAMES_CONTRACT.md` §11)

- Actions: `{"type": "pass", "cards": [3 card IDs]}` during the pass;
  `{"type": "play", "card": id}` during tricks.
- Visibility: your own hand is private to you; passed cards are revealed to
  the receiver only; plays to the current trick are public; completed tricks
  are fully public; opponent hands stay hidden (counts only).
- Faults: an invalid or failed decision records one fault for the seat and
  falls back deterministically — **pass the 3 lowest cards; play the lowest
  legal card** ("lowest" per clarification C4). `SandboxDown` is
  infrastructure failure: the match aborts and is never scored.

## Deviations from Hoyle (explicit and exhaustive)

- **D1 — one hand, not a 100-point game.** Hoyle plays hands until someone
  reaches 100 points. Stack Theory single-match mode plays exactly one hand
  of 13 tricks; winner = fewest penalty points, ties share. No hand
  rotation, no game-end threshold, no carry-over between hands.
- **D2 — pass direction fixed to left.** Hoyle rotates left → right →
  across → hold across the hands of a game. With one hand (D1) the rotation
  is meaningless; single-match mode always passes left.
- **D3 — no "no points on the first trick" bar.** Hoyle editions commonly
  forbid playing a penalty card (a heart or the Q♠) on the first trick
  unless the player holds nothing else. Stack Theory v1 does not enforce
  this: a seat void in the led suit on trick one may discard any card,
  penalty cards included. (The 2♣ itself still must open.)
- **D4 — no cards through the cut / no misdeals.** Hoyle's physical-table
  provisions — cutting the deck, exposed cards during the deal, misdeal
  remedies — do not apply: the deal is a seeded mechanical shuffle from
  `arena/games/common/deck.py`, which can neither expose a card nor short a
  seat. There is no cut step and no redeal path.
- **D5 — moon payout fixed.** Hoyle variants let the shooter either subtract
  26 from their own score or add 26 to everyone else's. Stack Theory v1
  fixes the payout: shooter 0, every other seat +26.
- **D6 — no Omnibus.** The J♦ −10 bonus and other scored-variant extras are
  out of scope; v1 is plain Hearts.
- **D7 — ties share the platform point.** Hoyle records equal low scores as
  a tied game; the arena splits one match point equally among tied winners
  (the `GAMES_CONTRACT.md` §5 convention).
- **D8 — deterministic fallbacks and a hard cap.** Hoyle is silent on broken
  agents; the platform requires a deterministic fault fallback (above) and a
  500-decision safety cap that this rules path can never reach.

## Clarifications (frequent house-rule ambiguity, fixed here)

- **C1 — what breaks hearts.** Only a heart played to a trick breaks hearts.
  The Q♠ never breaks hearts (it is a spade), and leading spades — even the
  Q♠ itself — is legal before hearts are broken.
- **C2 — the 2♣ lead is compulsory.** The 2♣ holder may not lead any other
  card to trick one, and no other seat leads it.
- **C3 — all-hearts hands.** A leader holding nothing but hearts may lead a
  heart; doing so also counts as breaking hearts.
- **C4 — "lowest" in fallbacks.** Lowest trick strength: 2 low, ace high,
  suit tie-break c < d < h < s.

Replay/result schemas and the visibility table are owned by
`GAMES_CONTRACT.md` §11; this document owns the game rules.
