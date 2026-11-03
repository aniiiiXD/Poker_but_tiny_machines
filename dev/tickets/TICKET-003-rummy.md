# TICKET-003 — Rummy agent: 13-card Indian Rummy
**Status:** gated (2026-11-03 — watchdog pass: 30/30 rummy tests, suite 255 passed with only Hexchange's in-flight tests failing, ruff clean, allowed-paths verified)

**Goal:** `backend/arena/games/rummy/` — 13-card Rummy, 2–6 seats. Rules doc first:
deal, turn (draw from stock/discard → meld/keep → discard), valid declaration
(≥2 sequences, ≥1 pure), points, drop mechanics, fault fallback, cap.

**Deliverables:** engine + baselines (meld-first, hold-back, discard-pressure) +
starters + visibility table (hands + stock hidden, discard pile public) + tests:
determinism, conservation, meld validation (pure vs impure sequences, sets, jokers),
declaration timing, wrong-declaration penalty, cap.

**Done-when:** watchdog gates pass; scored round with 2–6 entrants green.
