# Modeling the models — theory → Campus Arena engineering

How each research line becomes something we can actually build. Every model
here must live inside the platform's physical constraints:

- **1 ms** decision wall-time inside the sandbox (supervisor-enforced)
- single Python file ≤ **100 KiB**, **stdlib only**, no network, fresh
  container per table
- 2–8 seats, no-limit Hold'em, blinds 10/20 doubling every 25 hands,
  exact ICM at hand cap, points [8,5,3,2,1,0,0,0]
- fully deterministic seeded engine → **paired-seed evaluation is free**

The modeling principle that falls out of `WHAT_WE_LEARNT.md`: at 1 ms there
is no runtime search and no runtime inference. Every strong system in the
literature is either (a) a **distilled blueprint** (CFR-family), (b) a
**cheap adaptive rule** (no-regret family), or (c) **learned offline, frozen
at runtime** (DouZero/AlphaHoldem family). We build all three families.

---

## Family 1 — Blueprint bots (CFR distilled to tables)

**Papers:** `zinkevich_2007__cfr.pdf`, `tammelin_2014__cfr_plus.pdf`,
`lanctot_2009__mccfr.pdf`, `brown_sandholm_2019__discounted_cfr.pdf`,
`xu_2022__autocfr.pdf`, `brown_2019__deep_cfr.pdf`.

**The model.** Offline (unlimited compute, our host), run tabular MCCFR on an
*abstracted* game, then distill the average strategy into lookup tables the
bot reads at runtime.

- Card abstraction: preflop = the 169 hand classes; postflop = bucket hands
  by (made-hand strength, draw potential) into ~64–256 buckets per street
  (potential-aware beats strength-only — Waugh's pathologies warn to
  validate off-tree).
- Bet abstraction: fixed bet-size ladder per street (e.g., {⅓, ⅔, 1× pot,
  all-in} × stack-depth band).
- Solve with CFR+ / DCFR (AutoCFR's lesson: *tune the variant per game* —
  our blinds-double-every-25-hands non-stationarity is exactly the regime
  where variants diverge).
- **Distillation & size:** store per (bucket, street, position-band,
  pot-type) a strategy vector over the bet ladder. 100 KiB is comfortable:
  ~8×64×4×6×4 vectors of 6 floats, quantized to uint8 ≈ 50 KiB.

**Teaching artifact:** a Kuhn-poker CFR solver in the starter kit — ~60 lines,
exact bluff frequency 1/3 visible by hand. This is the "aha" that makes the
whole literature click for students.

**Runtime cost:** array lookup + linear interpolation ≈ microseconds. Fits
1 ms with two orders of magnitude to spare.

## Family 2 — No-regret adaptive bots (V-learning flavored)

**Papers:** `jin_2023__v_learning_decentralized_marl.pdf`,
`bai_jin_yu_2020__self_play.pdf`, `song_2021__general_sum_markov_games.pdf`,
`jin_2022__power_of_exploiter.pdf`.

**The model.** V-learning says: *independent* learners running a no-regret
subroutine over their own action payoffs learn Nash/CCE-level play without
modeling opponents. Concretely, per information-set bucket keep:

```
weights[action] *= exp(eta * normalized_payoff(action))   # Hedge
policy = weights / sum(weights)                            # + epsilon floor
```

- Payoffs estimated from hand outcomes streamed through the bot's own
  history (stdlib: deque + counters).
- Discount old evidence: blinds double every 25 hands → the environment is
  non-stationary by design; a fixed learning rate that *forgets* is correct
  here, not a bug.
- ε-mixing floor on near-indifference decisions (principle 5): prevents the
  rock-paper-scissors exploitation of deterministic bots.

**Size/cost:** a few hundred floats → bytes; one pass over ≤6 actions per
decision → microseconds.

## Family 3 — Population / exploiter bots (PSRO-lite)

**Papers:** `lanctot_2017__psro.pdf`, `jin_2022__power_of_exploiter.pdf`,
plus Nowak's evolutionary-robustness results (paywalled; synthesized in
`WHAT_WE_LEARNT.md`).

**The model.** The exhibition pool is a *population*, not a fixed roster:

1. Every N practice runs, fit an opponent model from our own replays
   (action frequencies per street/position/pot-type bucket).
2. Train a best response against that mixture (a short offline MCCFR run in
   the abstracted game).
3. Add it to the pool; cull dominated strategies (meta-game matrix from
   paired-seed round-robins we already have).

This is PSRO with our replay store as the meta-game oracle. Evolutionary
guardrail: keep a diversity floor — a pool that collapses to one archetype
is trivially exploitable by design (Nowak's drift lesson).

## Family 4 — What NOT to do at 1 ms (and the legal middle ground)

**Papers:** `brown_sandholm_2017__safe_nested_subgame_solving.pdf`,
`schmid_2023__student_of_games.pdf`, `schmid_2021__player_of_games.pdf`,
`moravcik_2017__deepstack.pdf`.

- Runtime search over public belief states (ReBeL/SoG) and continual
  re-solving (DeepStack/Libratus) are **out of budget** — they define the
  frontier but need seconds, not milliseconds.
- Legal middle ground: **pre-resolved endgame charts** — depth-limited
  solving distilled the same way as Family 1, keyed on (stack_bb, pot_bb,
  street, bucket). This is Libratus's "nested endgame" idea, precomputed.
- Anti-pattern (documented for students): PIMC/determinizing opponents'
  hidden cards is unsound in general and *measurably* exploitable in
  multiway pots — the exhibition pool should include a deliberately
  determinizing strawman so students can see the pathology.

## Family 5 — Learned policies (the model track)

**Papers:** `zha_2021__douzero.pdf`, `zhao_2024__pokergpt.pdf`,
`xie_2020__suphx.pdf`, `zha_2020__rlcard.pdf`, `bai_2022__extensive_form_imperfect_info.pdf`.

The participant-facing track (BACKLOG priority 2) maps directly:

- **DouZero template:** deep Monte-Carlo self-play — no search, simple
  value targets, works for multiplayer with teams/against-field structure.
- **AlphaHoldem template:** end-to-end self-play RL reaching solver-class
  play at **2.9 ms** inference — proof that learned policies fit our weight
  class.
- **Suphx rules adopted as platform policy:** oracle features (true hole
  cards, deck order) may exist *in training data only*; runtime observation
  contract stays anonymous — our sandbox already enforces this boundary, the
  dataset must too (decision rows carry only the acting player's cards).
- **Artifact policy:** our `model_projects.py` already bounds multi-file
  projects at 2 MiB with zip-safety; weights as JSON/npz-style data, no
  runtime fetches (never fetch arbitrary model files during a live game).
- Bai et al. ICML 2022 gives us the *claim students can make*: near-optimal
  extensive-form learning is sample-feasible — so a course-scale compute
  budget is not a valid excuse for a terrible agent.

## Evaluation models (measure goodness, don't guess it)

**Papers:** `sidford_2020__stochastic_games_near_optimal.pdf`,
`zhang_2019__lq_games_nash.pdf`, plus AIVAT (paywalled) and the paired-seed
point in `WHAT_WE_LEARNT.md` principle 10.

1. **Exploitability proxy (NashConv-lite).** Exact best responses are
   intractable in our game; fit instead a *bucketed best response* against
   each bot's observed action frequencies per (street, position, pot-type,
   stack-band) cell from replays, and evaluate that response over ~10⁴
   paired-seed hands. Report `exploitability ≈ BR_profit / hands` on profile
   and event pages.
2. **Paired seeds (poor-man's AIVAT).** Our engine is deterministic: the same
   seed + lineup + stacks replays exactly. Compare two bots on identical
   deals (common random numbers) → variance collapses, comparisons need
   ~10× fewer hands.
3. **Anchors & Elo.** Keep a frozen anchor set (Family-1 blueprint at three
   quality tiers + Family-2 adaptive). All rankings are Elo against anchors
   with CIs; anchor exploitsability is published so "good" has a number.

## Dataset modeling (poker-data/ alignment)

The generator's decision rows are already the training format for both
families above:

- (observation, action) pairs → **behavioral cloning** warm-start (Family 5)
- grouped by info-set bucket with outcomes → **offline V-learning** /
  CFR-on-data (Family 1/2)
- category tags = the theory taxonomy: street, pot-type (limped / SRP /
  3bet+), stack depth (bb), blind level, ICM-pressure tier, position,
  table size, archetype. Uniqueness + stratification implement principles
  8 (capacity/diversity) and 9 (population coverage).

## Build order

| # | Deliverable | Family | Effort |
|---|---|---|---|
| 1 | Kuhn-poker CFR solver + notebook in starter kit | 1 | small |
| 2 | `MixedBaseline` (ε-floor) + `PotOddsFloor` archetype | 1/2 | small |
| 3 | `HedgeBot` no-regret archetype (stdlib) | 2 | medium |
| 4 | Bucketed abstraction + tabular MCCFR offline trainer (host-side, in poker-data/) | 1 | large |
| 5 | Exploitability-proxy harness + paired-seed runner | eval | medium |
| 6 | PSRO-lite exhibition pool refresh from replays | 3 | medium |
| 7 | Model-track submission categories + artifact rules | 5 | medium (mostly policy) |

Items 2, 3, 5 are pure backend/arena + poker-data work and unlock a
measurably stronger arena immediately; item 4 is the first "solved-ish"
baseline we can publish as the thing to beat.
