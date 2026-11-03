# TICKET-002 — UNO agent: rules prototype (M4)
**Status:** gated (2026-11-03 — watchdog pass: 28/28 uno tests, full suite 196/196, ruff clean, allowed-paths verified) · **Blocked by:** TICKET-001 (gated ✓)

**Goal:** `backend/arena/games/uno/` — the familiar UNO experience as an exact,
source-cited rules prototype. Write the rules doc BEFORE code: deck composition
(108 cards), 2–4 seats, legal plays, action-card effects, draw and playable-draw,
wild color state, draw-four legality/challenge, UNO declaration, two-player
behavior, turn direction, deck exhaustion, end-of-hand scoring, fault fallback,
termination cap.

**Hard rules:** cite the selected rules; list every deviation explicitly; do NOT
call it official; no proprietary art; original placeholder visuals only. Label in
the UI as a prototype. Trademark review is a human gate before any public branding.

**Deliverables:** engine + baselines (≥3 styles) + single-file and model starters +
visibility table (hands hidden, wild color public) + contract-conformance tests
(determinism, conservation, wild/reverse/skip/draw effects, last-card edge, cap).

**Done-when:** watchdog gates pass (leak scan on full serialized API response,
protocol entry proposed to orchestrator, 108-card conservation).
