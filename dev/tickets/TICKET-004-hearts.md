# TICKET-004 — Hearts agent: 4-seat trick avoidance
**Status:** gated (2026-11-03 — watchdog pass: 23/24 hearts tests +1 numpy-skip, full suite 196/196, ruff clean, allowed-paths verified)

**Goal:** `backend/arena/games/hearts/` — classic Hearts, 4 seats. Rules doc first:
deal 13×4, pass phase (left/right/across/hold rotation), 2♣ leads, follow-suit
constraints, hearts-break, Q♠, shooting the moon, 100-point game end (single-match
mode: fixed 13 tricks = structurally bounded, NO artificial decision cap).

**Deliverables:** engine + baselines (safe-dumper, moon-hunter, Q♠-dodger) +
starters + visibility table (hands hidden, passed cards revealed to receiver,
tricks public once complete) + tests: determinism, conservation, follow-suit
legality, break-hearts rule, moon scoring, pass rotation across hands.

**Done-when:** watchdog gates pass; trick-cycle motif extracted proposal filed to ⑦.
