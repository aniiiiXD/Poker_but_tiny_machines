# TICKET-001 — Deck agent: shared token engine
**Status:** gated (2026-11-03 — watchdog pass: 19/19 deck tests, full suite 145/145, ruff clean, allowed-paths verified) · **Blocks:** 003, 004, 005

**Goal:** `backend/arena/games/common/deck.py` — the one card/token engine every
deck game builds on. Stdlib only, fully deterministic (all randomness via a
passed-in `random.Random(seed)`).

**Deliverables**
- `standard_deck()` → 52 card IDs per contract (`{rank}{suit}`, ranks `A23456789TJQK`, suits `cdhs`)
- `Deck(tokens, seed)` — seeded shuffle, `draw(n)`, `discard(cards)`, `remaining`, `deal(seats)` (round-robin)
- `Hand` — ordered multiset: add/remove/contains/count, pluggable sort key (contract default exported)
- `Pile` — face-down stack: add, `take_all()`, size
- `backend/tests/test_deck.py` — determinism (same seed ⇒ identical order), 52-card
  conservation through dealing, draw-until-empty raises, hand/pile ops

**Allowed paths:** `backend/arena/games/common/*`, `backend/tests/test_deck.py` — nothing else.
**Done-when:** pytest green, `ruff check` clean, contract sort-key test passes.
