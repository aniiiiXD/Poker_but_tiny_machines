# Stack Theory Rummy v1 — Rules (rules_version 1)

Indian 13-card Rummy on two decks, as a Stack Theory arena prototype.
Not affiliated with any commercial rummy platform; no proprietary art.
This document was written before the engine code and is the freeze the
engine implements. Every deviation from the cited rules is listed
explicitly in **Deviations** at the bottom.

## Source followed

The meld, joker, and scoring rules follow the standard tournament rules for
Indian 13-card Rummy as published by mainstream Indian online-rummy
platforms (the widely reproduced "How to play" rules of RummyCircle-style
tables) and as summarized on Wikipedia's *Indian rummy* article:

- 13 cards per player from a double deck including printed jokers.
- One face-up card fixes a **wild rank**; every suit of that rank plays as
  a joker for the whole match.
- To win a hand a player must hold at least **two sequences, at least one
  of them pure** (no jokers), with all cards grouped into sequences
  (3+ consecutive cards of one suit) or sets (3–4 cards of one rank).
- Card points: Ace/King/Queen/Jack/Ten = 10, number cards = face value,
  jokers = 0.

Where those sources differ among themselves (set-size limits with two
decks, wild-flip procedure, wrong-show penalties), this document fixes one
deterministic choice and records it as a deviation.

## Table

- **Seats 2–6.** Every player is dealt 13 cards from a shuffled 106-card
  shoe dealt through the shared deck engine (`games/common/deck.py`).
- **Shoe (106):** two standard 52-card decks plus two printed jokers
  `XJ1` and `XJ2`. Contract card identity (`GAMES_CONTRACT.md` §2) gives
  both copies of a natural card the same ID, so the shoe is a multiset:
  each natural card exists exactly twice, each printed joker once.
- **Wild rank:** after the deal, cards are flipped off the stock until a
  natural card appears; that card's rank is the public wild rank for the
  match, and the flipped card returns to the bottom of the stock (all
  suits of that rank, both copies, act as jokers).

## Turn

On your turn, in this order:

1. **Draw** — take the top card of the stock or the top card of the
   discard pile: `{"type":"draw","from":"stock"|"discard"}`.
2. **Declare (optional, only at 14 cards)** — either
   `{"type":"declare","hand":[14 ids]}` naming exactly the 14 cards you
   hold, or `{"type":"pass"}`.
3. **Discard** — end the turn by discarding one owned card:
   `{"type":"discard","card":id}`. The hand returns to 13 cards and play
   passes clockwise.

A successful declaration replaces the discard step and ends the match.

## Melds (the declaration shape)

A **declaration** is legal when the shown 14 cards partition completely
into groups where:

- **Sequence** — 3 or more cards of one suit with consecutive ranks. Aces
  play low (A-2-3) and high (Q-K-A); K-A-2 is never a sequence. A
  **pure** sequence contains no joker cards at all (a wild-rank card
  inside a run turns it into an impure sequence, even if it fits
  naturally). An **impure sequence** fills its gaps with joker cards.
- **Set** — 3 or 4 cards of one rank; natural cards in the set must carry
  distinct suits (with two decks, `5c 5c 5d` is invalid). Jokers may
  substitute for missing ranks.
- **Joker cap** — at most **2 joker cards** (printed or wild-rank) inside
  any single meld; a meld made only of jokers is invalid, and a group
  with exactly one natural card counts as a set, never a sequence.
- **No duplicate card IDs inside a meld** (two decks make duplicates
  possible; they may never share one meld).
- At least **two groups must be sequences**, and at least **one of them
  pure**.

The engine validates a declaration by a deterministic bounded search over
all meld partitions of the 14 shown cards (deviation 3).

## Wrong declaration

A declaration whose 14 shown cards match the player's hand but admit no
legal grouping is a **wrong declaration**: it records one **fault** for
the seat, adds **20 penalty points** to that seat's deadwood at the cap,
and the shown hand becomes public (history event) — the turn then
continues with the mandatory discard. Malformed actions (unowned cards,
wrong counts, wrong types) are plain faults with the deterministic
fallback and carry no penalty.

## Points and the decision cap

- **Card points:** jokers 0; A/K/Q/J/T 10; number cards face value.
- **Decision cap 500.** When the cap is reached, play stops at the next
  13-card turn boundary and hands are scored as they stand:
  - a hand that could be declared in full scores **0 deadwood**;
  - any other hand scores the **full point value of all its cards**,
    plus 20 per wrong declaration that seat made;
  - the **lowest deadwood wins**; ties share the win.

## Deck exhaustion

When a stock draw finds the stock empty, all discard cards **except the
top card** are shuffled (with the match's private seeded stream) into a
new stock and the draw proceeds. If no card lies under the top, a stock
draw is illegal: it records a fault and the deterministic fallback draws
the public discard top instead.

## Faults and fallbacks

Invalid actions, wrong types, and timeouts record one **fault** for the
acting seat and fall back deterministically:

- draw decision → draw from the stock (or the discard top when the stock
  is unavailable);
- declare decision → `pass`;
- discard decision → the lowest owned card by the contract sort key
  (printed jokers sort last).

`SandboxDown` is infrastructure: the match aborts and is never scored.

## Visibility table (the freeze)

| Information                          | Visibility                  |
|--------------------------------------|-----------------------------|
| Own hand                             | private(seat)               |
| Opponent hands                       | hidden                      |
| Stock order                          | hidden                      |
| Stock remaining count                | public                      |
| Discard top card                     | public                      |
| Discard pile below the top card      | hidden                      |
| Wild rank                            | public                      |
| All hand counts                      | public                      |
| Draw events (source; the public card taken off the discard top) | public |
| Discard events                       | public                      |
| Declared hands (valid or wrong)      | public at declaration       |
| Reshuffle events (that one happened) | public                      |
| Active seat / turn type              | public                      |

## Deviations from the cited rules

1. **Two decks share card IDs.** Contract card identity makes both copies
   of a natural card the same string, so the shoe is a multiset:
   duplicates are legal across the table but never inside a single meld.
2. **A declaration groups all 14 cards.** Real tables meld 13 cards and
   slip the 14th face-down to a finish slot; the frozen contract declares
   with all 14 card IDs, so all 14 must form valid groups.
3. **Players do not submit groups.** The engine validates declarations by
   a deterministic bounded search over meld partitions; the action
   payload carries only the 14 card IDs.
4. **Discard pile below the top card is hidden.** Real tables play the
   whole discard pile face up; the contract freeze makes only the top
   card public.
5. **Wild-rank flip.** The wild rank is the rank of a card flipped from
   the stock after the deal; flipped printed jokers return to the stock
   bottom and the flip repeats. Real practices vary (dealt wild cards,
   re-flip to an Ace, and so on).
6. **Joker cap.** At most two joker cards may sit in any single meld and
   all-joker melds are invalid; published rules set no such cap. A group
   with exactly one natural card counts as a set, never a sequence.
7. **Sets are exactly 3–4 cards** and may not repeat a suit among their
   natural cards; published two-deck rules vary on both points.
8. **Aces count 10 points** at the cap (some tables count 1).
9. **Wrong declaration penalty.** One fault plus 20 cap points plus a
   public reveal, and play continues (real rules score the hand at the
   maximum and seat the player out for the hand).
10. **Cap scoring.** Play stops at the next 13-card turn boundary; a
    declarable hand scores 0, otherwise all cards count in full (real
    rules grant partial meld credit to hands holding a pure sequence —
    simplified here to one deterministic rule).
11. **Deck exhaustion.** Discards-except-top are reshuffled into the
    stock; with nothing to reshuffle a stock draw faults and falls back
    to the discard top. Real rules rarely define this corner.
12. **No drop mechanics.** Real Indian rummy's drop/chest penalties
    (20/40/75 points) are omitted in v1 single-match mode.
13. **Scoring.** Win 1 / loss 0, ties share the point (platform
    convention); real rummy settles on point sums across many hands.
