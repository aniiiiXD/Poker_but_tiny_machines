# What makes strategies good in stochastic games

A research synthesis across the MIT, Harvard, Russian, and Chinese schools,
curated for Stack Theory. Verified citations were checked against the web on
2026-10-31; the rest are canonical works cited from the literature.

Why this matters here: our arena is an 8-handed no-limit Hold'em tournament
with rising blinds and ICM scoring, students submit 1 ms/std-lib bots, and we
are building a large unique dataset of games. Every design decision below —
baseline archetypes, dataset categories, evaluation metrics — should trace
back to a theorem or a flagship-system lesson in this document.

---

## The shared canon (before the schools)

| Work | What it established |
|---|---|
| von Neumann, *Theory of Games* (1944) | Minimax: in zero-sum games, a safety value exists; mixing is mandatory |
| Kuhn, "A simplified two-person poker" (1950) | The minimal poker game; bluffing frequencies computable by hand |
| **Shapley, "Stochastic Games" (PNAS 1953)** | Invented stochastic games: Markov chain × matrix game; discounted zero-sum value exists via iteration (confirmed in Sidford et al. 2020 refs: PNAS 39(10):1095–1100) |
| Blackwell, "An analog of the minimax theorem for vector payoffs" (1956) | Approachability: the geometry behind all regret minimization |
| **Mertens & Neyman, "Stochastic games" (IJGT 1981)** | The value exists even *undiscounted* (limsup payoff); patience is enough |
| Hart & Mas-Colell, "Simple adaptive strategies" (Econometrica 2000) | Regret-matching converges to correlated equilibria — the engine inside CFR |
| Foster & Vohra, "Calibrated learning and correlated equilibrium" (GEB 1997) | Calibration ⇒ no one can exploit your predictions |
| Cesa-Bianchi & Lugosi, *Prediction, Learning, and Games* (2006) | The unified textbook: regret is THE performance metric for sequential decisions |

## The MIT thread

- **Constantinos Daskalakis, Goldberg, Papadimitriou — "The complexity of
  computing a Nash equilibrium" (STOC 2006 / SICOMP 2009), and Xi Chen &
  Xiaotie Deng (FOCS 2006).** Computing Nash in general games is PPAD-hard.
  *Lesson: never promise "solving" — promise small exploitability, measured.*
- **Sasha Rakhlin & Karthik Sridharan (MIT, online learning).** Regret rates
  are governed by variance/curvature: stochastic (i.i.d.-ish) opponents admit
  *faster* rates than adversarial ones. *Lesson: opponent modeling pays —
  treating the table as adversarial when it is learnable wastes regret budget.*
- **Kaiqing Zhang, Zhuoran Yang, Tamer Başar — "Policy optimization provably
  converges to Nash equilibria in zero-sum linear quadratic games"
  (NeurIPS 2019).** Nonconvex-nonconcave in policy space, yet gradient
  play converges globally to Nash when structure (LQ) exists. Also:
  "Model-based MARL in zero-sum Markov games with near-optimal sample
  complexity" (NeurIPS 2020 spotlight) and "Robust MARL with model
  uncertainty" (NeurIPS 2020). Zhang is now MIT faculty. *Lesson: exploit
  structure; plan for model error.*
- **MIT Pokerbots** — the annual imperfect-information bot competition that
  inspired this project's format (see REFERENCES.md).

## The Harvard thread

- **Drew Fudenberg & Eric Maskin — "The Folk Theorem in Repeated Games with
  Discounting..." (Econometrica 1986).** With enough patience, punishment and
  reputation make almost anything enforceable. *Lesson: discount factors and
  horizons change which strategies are even possible.*
- **Drew Fudenberg & David Levine — *The Theory of Learning in Games*
  (MIT Press 1998).** Good strategies are the *rest points of everyone's
  learning dynamics*. *Lesson: equilibrium is an outcome of learning, not a
  fixed script — your bot competes against learners, not oracles.*
- **Martin Nowak (Program for Evolutionary Dynamics, Harvard) & Sigmund —
  "A strategy of win-stay, lose-shift..." (Nature 1993); Nowak, Sasaki,
  Taylor & Fudenberg (Nature 2004).** In *finite, noisy* populations, the good
  strategies are the ones that resist invasion under drift — simple
  state-machines (Pavlov) can beat sophisticated ones. *Lesson: robustness is
  a population property; test against pools, not single opponents.*
- **Leslie Valiant (Turing Award, Harvard)** — PAC learning and evolvability:
  a strategy is only good *relative to the resource budget of the learner*.
  *Lesson: our 1 ms / std-lib constraint is part of the game definition.*
- Nearby Harvard threads: Na Li's group (policy optimization for multi-agent
  control), Nika Haghtalab (smoothed analysis of learning in games, while a
  Harvard Junior Fellow).

## The Russian thread

- **Andrey Markov (1906), Andrey Kolmogorov (1933).** The stochastic substrate
  itself: chains, measure-theoretic probability. Every "stochastic game" is a
  Markov process the moment strategies are fixed.
- **Pontryagin, Boltyanskii, Gamkrelidze, Mishchenko — *The Mathematical
  Theory of Optimal Processes* (1961).** The maximum principle: optimal
  control = adjoint (costate) variables telling you the shadow price of state.
  *Lesson: value-function gradients are the steering signal — the conceptual
  ancestor of actor-critic.*
- **Krasovskii & Subbotin — positional differential games (Ural school,
  1974; English: *Game-Theoretical Control Problems*, 1988).** Guaranteed
  control under worst case via "stable bridges" — backward-computed sets of
  winning states. *Lesson: the Russian answer to "what is good" is
  *guarantee-first*: a strategy is good if it keeps you inside the winning
  set against the worst adversary.*
- **Krinsky & Tsetlin (1963) — automata playing games.** Tiny finite-state
  learners converge to equilibrium play in repeated matrix games (Goore game).
  *Lesson: dumb incremental rules find good strategies — relevant to 1 ms bots.*
- **Vladimir Vapnik (VC theory, structural risk minimization).** Empirical fit
  alone fails off-distribution; control capacity. *Lesson: this is exactly
  "abstraction pathologies" (below) — a strategy tuned on observed opponents
  must not overfit them.*
- **Vladimir Vovk — aggregating algorithm (COLT 1990); game-theoretic
  probability with Shafer (*Probability and Finance: It's Only a Game!*, 2001);
  defensive forecasting.** A strategy is good when *no betting adversary can
  grow capital against it* — calibration as defense. *Lesson: unpredictability
  is a theorem, not a style.*
- **Leon Petrosyan (St. Petersburg) — cooperative dynamic games,
  time-consistency (e.g., Petrosyan & Zaccour, JEDC 2003).** A solution must
  remain optimal *as the game unfolds*; otherwise it will be renegotiated
  mid-stream. *Lesson: our ICM settlement at hand-cap is a time-consistent
  allocation; prize structures and freeze rules should be too (ours are:
  submissions frozen per round).*
- **Yuri Ermoliev — stochastic quasigradient methods (IIASA).** Optimization
  under noise via stochastic approximation; the engine under noisy search.

## The Chinese thread

- **Xi Chen & Xiaotie Deng — "Settling the complexity of computing two-player
  Nash equilibria" (FOCS 2006).** Two-player Nash is PPAD-complete. *Lesson:
  the yardstick must be ε-approximation + exploitability, never exactness.*
- **Yu Bai, Chi Jin, Tiancheng Yu — "Near-optimal reinforcement learning with
  self-play" (NeurIPS 2020); Jin, Liu, Wang, Yu — "V-Learning: a simple,
  efficient, decentralized algorithm for multiagent RL" (Math of OR 2023,
  arXiv 2110.14555).** V-learning: *independent* learners running no-regret
  bandit subroutines learn Nash (2p-0s) / CCE (multiplayer) with sample
  complexity scaling with max action space, not the joint action space —
  breaking the "curse of multiagency". *Lesson: you do NOT need to model
  opponents' policies to be near-optimal; you need no-regret updates per
  agent + exploration.*
- **Bai, Jin, Mei, Yu — "Near-optimal learning of extensive-form games with
  imperfect information" (ICML 2022).** The above theory reaches game trees
  (i.e., poker). Also "The Power of Exploiter" (Jin, Liu, Yu, ICML 2022):
  maintaining exploiters is provably powerful. *Lesson: a population with a
  best-response challenger is the right training/eval structure.*
- **Aaron Sidford, Mengdi Wang, Lin F. Yang, Yinyu Ye — "Solving Discounted
  Stochastic Two-Player Games with Near-Optimal Time and Sample Complexity"
  (AISTATS 2020, PMLR 108:2992–3002).** Settles the sample complexity of
  discounted zero-sum SGs up to polylogs via near-optimal Q-learning. *Lesson:
  provable planning/learning in SGs is sample-feasible.*
- **CASIA/Tsinghua poker line:** **AlphaHoldem** (Zhao, Yan, Li, Li, Xing —
  AAAI 2022, *Distinguished Paper*): end-to-end self-play RL for heads-up
  no-limit; trained in 3 days on one PC, decides in 2.9 ms on one GPU —
  >1000× faster than DeepStack. **AutoCFR** (Xu, Li, Fu, Fu, Xing — AAAI
  2022): meta-learns CFR variants. **PokerGPT** (2024): LLM as lightweight
  multiplayer solver. *Lesson: at real-time budgets, learned end-to-end
  policies can match solver-class play.*
- **DouZero** (Zha et al., ICML 2021): plain deep Monte-Carlo self-play
  mastered DouDizhu; **RLCard** (NeurIPS 2020 demo): the standard card-game RL
  toolkit. *Lesson: simple value-based self-play + clean tooling scales far.*
- **Suphx** (Microsoft, arXiv 2003.13590, 2020) — superhuman Mahjong:
  *oracle guiding* (train with privileged info, drop it at runtime), *global
  reward prediction* (turn-level → game-level scores), runtime feature
  adaptation. *Lesson: oracles are training scaffolds only — never at runtime
  (our sandbox enforces the same boundary).*
- **Yaodong Yang (PKU)** and others: population-based MARL and equilibrium
  finding (PSRO-style) as the practical training loop.

## The poker-AI arc (the flagship lessons)

1. **CFR** — Zinkevich, Johanson, Bowling, Piccione, "Regret minimization in
   games with incomplete information" (NeurIPS 2007): counterfactual regret
   decomposed *per information set*; time-average converges to ε-Nash.
2. **MCCFR** (Lanctot et al., 2009): sampling instead of full traversal.
3. **Abstraction pathologies** (Waugh, Schnizlein, Bowling, Szafron, AAMAS
   2009): more abstraction granularity can *hurt* off-tree — approximation is
   not monotone. Vapnik's warning, rediscovered in games.
4. **Data-biased robust CFR** (Johanson & Bowling, 2012): robustness in
   training data, not just opponent models.
5. **DeepStack** (Moravčík et al., *Science* 2017): continual re-solving with
   counterfactual value networks; lookahead + intuition, no full blueprint.
6. **Libratus** (Brown & Sandholm, *Science* 2018) — and the key technique
   **"Safe and nested subgame solving for imperfect-information games"**
   (NeurIPS 2017 best paper): re-solve subgames *against the full opponent
   strategy* with reach-weighted values, never naively; nested endgames.
7. **Pluribus** (Brown & Sandholm, *Science* 2019): multiplayer poker —
   blueprint + limited-depth real-time search + self-improvement against
   past selves. Multiplayer exploitability is subtle: a Nash profile is no
   longer a safety guarantee for everyone.
8. **ReBeL** (Brown, Lerer, Gross, Sandholm, ICML 2020): RL + search over
   *public belief states* — the clean unification.
9. **Player of Games / Student of Games** (Schmid et al., DeepMind,
   2021–2023) and **DeepNash** (Perolat et al., *Science* 2022, Stratego):
   GT-CFR-style unified algorithms across imperfect-info games.
10. **AIVAT** (Burch, Schmid, Moravčík, Morrill, Bowling, UAI 2018):
    variance-reduced unbiased evaluation — *measure skill with less noise*.
11. **PIMC pathologies** (Long, Sturtevant, Buro, Furtak, AAAI 2010) and
    IS-MCTS (Cowling et al., 2012): determinizing hidden information is
    sometimes fine and sometimes catastrophic — know which regime you're in.
12. Field evidence: Palacios-Huerta, "Professionals play minimax" (REStud
    2003, penalty kicks); Walker & Wooders, "Minimax play at Wimbledon"
    (AER 2001). Humans approximate mixing; bots should not be worse.
13. The practical bible: Chen & Ankenman, *The Mathematics of Poker* (2006) —
    pot odds, MDF, bluff-to-value ratios as exact frequencies (e.g., river
    bluff fraction = bet/(bet+pot) makes a bluff-catch indifferent).

---

## Synthesis: ten principles of good strategies in stochastic games

1. **Guarantee before profit.** Anchor at the minimax/game value
   (Shapley; Krasovskii's stable bridges). Exploit above the floor only with
   bounded downside (safe opponent exploitation).
2. **No regret ⇒ unexploitable in the limit.** If cumulative regret grows
   sublinearly (O(√T)), no adaptive opponent can extract more than O(√T).
   (Blackwell; Hart–Mas-Colell; CFR; V-learning.)
3. **Exact equilibrium is computationally out — ε is the standard.**
   PPAD-hardness (Daskalakis; Chen–Deng) ⇒ measure *exploitability / NashConv*,
   not "did we solve it".
4. **Decompose regret where the information lives.** Counterfactual regret per
   information set is why CFR works on game trees; per-agent V-learning is why
   decentralized self-play works in state-based games.
5. **Randomize your support, model their distribution.** Mix at the
   indifference frequencies (Kuhn; Chen–Ankenman); calibrate/defend
   (Vovk; Foster–Vohra). Nuance: in *large* games near-determinism is often
   fine (Suphx) because environment noise substitutes for mixing — but in
   *small repeated* games against learning opponents, deterministic bots are
   hard-coded losses.
6. **Patience changes what is enforceable.** Discounting and horizons reshape
   the strategy set (folk theorem). In tournaments, ICM is exactly
   chip-space risk aversion — our engine's [8,5,3,2,1,0,0,0] + ICM settlement
   is the discounting of poker.
7. **Time consistency.** Strategies and allocations must stay optimal as the
   game unfolds (Petrosyan; safe nested subgame solving is its poker form).
   Mid-game rule changes or mid-round bot swaps break it — our per-round
   frozen snapshots exist for this reason.
8. **Sample efficiency and capacity control.** Near-optimal rates exist
   (Sidford–Wang–Yang–Ye; V-learning) but only if representation capacity is
   controlled (Vapnik); over-abstracted or overfit strategies fail
   off-distribution (abstraction pathologies).
9. **Robustness is a population property.** Test against pools + best-response
   challengers (PSRO; "Power of Exploiter"); invasion-resistance under noise
   (Nowak); robustness to model error (robust MARL, Zhang et al.).
10. **Evaluation is part of the strategy.** Low-variance, paired-seed,
    exploitability-aware measurement (AIVAT; common random numbers).
    Deterministic engines (ours) make paired comparisons nearly free.

## Applying this to Stack Theory

- **Baselines:** current 8 archetypes are deterministic ⇒ trivially
  counterable. Add (a) an ε-mixing floor on near-indifference decisions,
  (b) a pot-odds "safety floor" caller (never worse than check/fold EV rules),
  (c) an adaptive no-regret archetype (weighted-majority over actions per
  info-set bucket — Tsetlin/V-learning flavored, well within 1 ms), and
  (d) a PSRO-lite exhibition pool that periodically adds best-response
  challengers.
- **Evaluation:** add an exploitability-proxy harness — Monte-Carlo best
  response against each bot's observed action frequencies per street/position
  bucket; report NashConv-style scores on event pages. Use paired seeds
  (common random numbers) across tables for low-variance comparisons.
- **Dataset (poker-data/):** the category taxonomy above *is* the tagging
  scheme: table size, street, pot type (limped/single-raised/3bet/4bet+),
  stack depth (bb), blind level, ICM pressure tier, position, archetype —
  plus the decision rows as (observation, action) pairs for the model track.
- **Rules:** 1 ms decisions ⇒ blueprint-quality rules, no search; tabular and
  linear no-regret methods are the right weight class (AlphaHoldem's 2.9 ms
  shows even learned policies fit such budgets).
- **Trust:** hash-chained scoring + frozen submissions = time-consistency by
  construction; keep it.

## Short reading list

- Shapley (1953), Mertens & Neyman (1981), Solan & Vieille survey (PNAS 2015)
- Zinkevich et al. (2007); Lanctot et al. (2009, 2017); Waugh et al. (2009)
- Moravčík et al. (2017); Brown & Sandholm (2017, 2018, 2019); Brown et al. (2020)
- Bai, Jin, Yu (2020); Jin, Liu, Wang, Yu (2023); Bai, Jin, Mei, Yu (2022)
- Sidford, Wang, Yang, Ye (2020); Zhang, Yang, Başar (2019)
- Fudenberg & Levine (1998); Fudenberg & Maskin (1986); Nowak & Sigmund (1993)
- Krasovskii & Subbotin (1974/1988); Vapnik (1998); Vovk (1990, 2001)
- Chen & Ankenman (2006); Cesa-Bianchi & Lugosi (2006)
