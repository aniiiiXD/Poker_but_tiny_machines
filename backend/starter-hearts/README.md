# Hearts starter kit (Stack Theory Hearts v1)

Hearts is the classic trick-avoidance game: taking tricks is bad, penalty
cards are worse. Every hand, you pass three cards away, then 13 tricks are
played. Each heart you take costs 1 point, the Q♠ costs 13, and the player
with the fewest points wins. Take all 26 and you have "shot the moon" — you
score 0 and everyone else scores 26.

## Rules (Stack Theory Hearts v1)

- Four seats, standard 52-card deck, 13 cards each (one hand, 13 tricks —
  not the multi-hand 100-point game).
- **The pass:** before trick one, submit `{"type": "pass", "cards": [...]}` —
  exactly 3 cards you own. All seats choose simultaneously; your incoming
  cards are revealed to you alone once everyone has submitted. Single-match
  mode always passes left (seat *i* passes to seat *i + 1*).
- **The play:** the 2♣ holder must lead it to trick one. On your turn play
  `{"type": "play", "card": id}`. Follow suit is mandatory when you can.
  Hearts cannot be *led* until a heart has been played to a trick ("broken");
  an all-hearts hand may lead a heart. Leading spades — even the Q♠ — needs
  no broken hearts.
- The highest card of the led suit wins the trick and leads the next one.
  A seat void in the led suit may dump any card, penalty cards included.
- **Scoring:** hearts 1 point each, Q♠ 13. Fewest points wins; ties share
  the match point. Shooting the moon (all 26 points): shooter 0, others 26.
- Invalid actions or timeouts count as faults and fall back to a
  deterministic legal move (pass the 3 lowest; play the lowest legal card).

## What your bot sees

Only public information plus your own hand: card counts and points taken,
the current trick's plays, all completed tricks, the hearts-broken flag, and
the 3 cards passed to you. Never the seed, the deck order, or opponent hands.

## Files

- `agent.py` — a documented starter you can submit as-is, then improve.
- Edit locally, then upload in the Workshop (choose the Hearts game) or push
  `agent.py` to a connected GitHub repository.

## Strategy ideas

- Pass your Q♠ (or guard it with low spades if you must keep it), high
  hearts, and cards that create a void you can exploit.
- Duck under the current winner with your highest safe card — "lose
  expensively" — and keep low cards to escape tricks entirely.
- Count hearts: once all 13 have appeared, leading hearts is safe.
- Watch for moon shooters: a seat that wins every trick is collecting points;
  dump a heart on their tricks to break the moon.
