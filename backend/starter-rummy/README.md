# Rummy starter kit (Stack Theory Rummy v1)

Indian 13-card Rummy on two decks: build sequences and sets, then declare
before anyone else. On your turn you draw one card (from the closed stock or
the public discard top), may declare with all 14 cards, and must discard one
card to end the turn.

## Rules (Stack Theory Rummy v1)

- 2–6 seats, 13 cards each from a 106-card shoe: two standard decks (every
  natural card exists twice) plus printed jokers `XJ1` and `XJ2`.
- One public **wild rank** is flipped at the start: every card of that rank
  (all suits, both copies) plays as a joker alongside the printed jokers.
- A legal declaration groups **all 14 cards** into sequences and sets with
  at least **two sequences, one of them pure** (no jokers). Sequences are
  3+ same-suit consecutive ranks (aces go low A-2-3 and high Q-K-A, never
  wrapping K-A-2). Sets are 3–4 cards of one rank with distinct natural
  suits. At most **2 jokers per meld**; an all-joker meld is invalid.
- A wrong declaration (14 cards that cannot form that shape) records a
  fault, adds 20 cap points to your deadwood, and reveals your hand to
  everyone — then you still discard.
- Stock empty? All discards except the top card are shuffled into a new
  stock. After the 500-decision cap the lowest deadwood wins and ties share.
- Card points at the cap: jokers 0, A/K/Q/J/T 10, number cards face value.

## What your bot sees

Your own hand, the public discard top, the wild rank, everyone's card
counts, the stock's remaining size, and the public event history. Never the
stock order, the discards below the top card, or another seat's cards.

## Files

- `agent.py` — a documented starter you can submit as-is, then improve. It
  draws the upcard when it connects with your hand, sheds its loosest high
  cards, protects jokers, and declares only after verifying a full grouping
  (so it never suffers the wrong-declaration penalty).
- Edit locally, then upload in the Workshop (choose the Rummy game) or push
  `agent.py` to a connected GitHub repository.

## Strategy ideas

- Chase the second sequence first: a pure run plus any second sequence is
  the hard part; jokers can finish sets later.
- Track which wild-rank and printed jokers have been discarded — the
  history events name every public discard.
- Watch who takes the upcard: their draws tell you which ranks are dead in
  their hands, so discard ranks they have shown no interest in.
- Keep high cards only while they connect; at the cap they cost 10 points
  each.
