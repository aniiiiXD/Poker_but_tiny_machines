# Bluff starter kit (Stack Theory Bluff v1)

Bluff (also known as Cheat or I Doubt It) is a game of disciplined lying.
On your turn you place 1–4 cards face down and claim they are the required
rank; you may lie. Every other player then decides clockwise whether to
challenge. A caught liar picks up the whole face-down pile; a wrong challenge
costs the challenger the same pile.

## Rules (Stack Theory Bluff v1)

- Four seats, standard 52-card deck, 13 cards each. Required rank starts at
  Ace and advances one step per batch: A → 2 → … → K → A.
- On a play turn, submit `{"type": "play", "cards": [...]}` with 1–4 cards
  you own (by their card IDs). You may lie about their rank.
- Other players then decide in clockwise order, starting with the next seat:
  `{"type": "challenge"}` or `{"type": "pass"}`. The first challenge stops
  the sequence. If everyone passes, the play stays face down.
- On a challenge, the challenged batch is revealed. If any card differs from
  the claimed rank, the claimant takes the pile; otherwise the challenger
  does. Only that batch is revealed — older pile cards stay hidden.
- After a resolution the required rank advances and play passes to the seat
  after the claimant. A player who empties their hand wins — but only after
  all challenge decisions resolve and their hand is still empty.
- After the 500-decision cap, the current claim and its challenges finish; the player with the fewest cards wins if nobody has already won; ties share
  the point. Invalid actions or timeouts count as faults and fall back to a
  deterministic legal move (your sorted-lowest card, or pass).

## What your bot sees

Only public information plus your own hand: card counts, declared ranks,
challenge decisions that already happened, and revealed challenged batches.
Never the seed, deck order, opponent hands, or face-down pile contents.

## Files

- `agent.py` — a documented starter you can submit as-is, then improve.
- Edit locally, then upload in the Workshop (choose the Bluff game) or push
  `agent.py` to a connected GitHub repository.

## Strategy ideas

- Track how many copies of each rank have been publicly revealed; claims that
  exceed the remaining copies are provable lies.
- Bluff in small doses: one card bluffs are cheap to lose.
- Remember who passed: several passes in a row signal fear — or a trap.
