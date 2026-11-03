# TICKET-005 — Catan agent: hex trader (inspired-by, renamed)
**Status:** in-progress (spawned 2026-11-03 — contract §12 visibility table frozen) · **Blocked by:** nothing (own resource tokens; does not use TICKET-001)

**Goal:** `backend/arena/games/catan/` — social hex-island trading game INSPIRED BY
Catan. **Do not use the Catan name in UI/registry** — working title
"Hexchange v1"; "inspired by the classic trading board game" framing. No
proprietary art.

**Rules doc first:** hex board topology (seeded layout), number tokens + dice,
settlement/road placement legality, resource production, the robber, dev deck,
VP target termination. **Negotiation overlay (the novel part):** trade offers are
structured edges in a finite vocabulary — `offer{give→want}` / `accept` /
`reject` / `counter{...}` — between seat nodes during a trade phase; no free
text between bots.

**Deliverables:** engine + baselines (expander, trader, robber-hater) + starters +
visibility table (hands hidden, board + offers public) + tests: determinism,
board legality, production dice distribution, trade-edge lifecycle, robber rules,
VP termination, cap.

**Done-when:** watchdog gates pass; a 3-bot match completes with at least one
accepted trade and one robber move.
