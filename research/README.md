# Research library

Original papers (downloaded from open repositories: arXiv, PMLR, NeurIPS
proceedings, AAAI CDN), the synthesis of what they teach, and the modeling
guide that turns the theory into Campus Arena features.

| File | What it is |
|---|---|
| [`WHAT_WE_LEARNT.md`](WHAT_WE_LEARNT.md) | Cross-school synthesis (MIT/Harvard/Russian/Chinese) + ten principles |
| [`MODELING_GUIDE.md`](MODELING_GUIDE.md) | How to model the models: theory → concrete bots, eval, dataset, model track |
| [`papers/`](papers/) | 23 original papers (PDFs below) |
| [`paywalled_and_books.md`](paywalled_and_books.md) | Canon we cannot host (publisher-paywalled) with external links |

Papers are redistributed here for research/reference use; copyright stays with
the original authors and publishers. Files came from the venues' own open
servers or arXiv, which permits redistribution.

## papers/ — by school

### Foundations & shared canon

| File | Paper | Lesson in one line |
|---|---|---|
| `zinkevich_2007__cfr.pdf` | Zinkevich, Johanson, Bowling, Piccione — *Regret Minimization in Games with Incomplete Information*, NeurIPS 2007 | Counterfactual regret per information set; average strategy → ε-Nash. The workhorse of poker AI |
| `tammelin_2014__cfr_plus.pdf` | Tammelin — *Solving Large Imperfect Information Games Using CFR+*, arXiv 2014 | CFR+ — the practical speedup behind the first near-solving of HUNL |
| `lanctot_2009__mccfr.pdf` | Lanctot, Waugh, Zinkevich, Bowling — *Monte Carlo Sampling for Regret Minimization in Extensive Games*, NeurIPS 2009 | Sample instead of traverse — makes regret minimization scale |
| `lanctot_2017__psro.pdf` | Lanctot et al. — *A Unified Game-Theoretic Approach to Multiagent RL (PSRO)*, NeurIPS 2017 | Populations + best responses: robustness is a population property |
| `brown_sandholm_2017__safe_nested_subgame_solving.pdf` | Brown & Sandholm — *Safe and Nested Subgame Solving for Imperfect-Information Games*, NeurIPS 2017 (best paper) | Re-solve subgames against the *full* opponent strategy, never naively — Libratus's core |
| `brown_sandholm_2019__discounted_cfr.pdf` | Brown & Sandholm — *Solving Imperfect-Information Games via Discounted Regret Minimization (DCFR)*, AAAI 2019 | Weighting regret across iterations beats vanilla CFR in practice |
| `sidford_2020__stochastic_games_near_optimal.pdf` | Sidford, Wang, Yang, Ye — *Solving Discounted Stochastic Two-Player Games with Near-Optimal Time and Sample Complexity*, AISTATS 2020 | Sample complexity of zero-sum stochastic games settled up to polylogs |
| `schmid_2021__player_of_games.pdf` | Schmid et al. — *Player of Games*, arXiv v1 (2021) | Search over public belief states works across perfect + imperfect info |
| `schmid_2023__student_of_games.pdf` | Schmid et al. — *Student of Games*, Science Advances 2023 (v2 of the same line) | The mature unified GT-search algorithm; CFR-based search is *sound* where MCTS is not |
| `moravcik_2017__deepstack.pdf` | Moravčík et al. — *DeepStack*, arXiv 2017 (Science version paywalled) | Continual re-solving + counterfactual value networks; lookahead + intuition |

### MIT thread

| File | Paper | Lesson |
|---|---|---|
| `zhang_2019__lq_games_nash.pdf` | Zhang, Yang, Başar — *Policy Optimization Provably Converges to Nash Equilibria in Zero-Sum Linear Quadratic Games*, NeurIPS 2019 | Nonconvex-nonconcave, yet gradient play converges globally when structure exists |
| `zhang_2020__model_based_zero_sum_sg.pdf` | Zhang, Kakade, Başar, Yang — *Model-Based Multi-Agent RL in Zero-Sum Markov Games with Near-Optimal Sample Complexity*, NeurIPS 2020 | Model-based planning reaches optimal sample complexity in stochastic games |

### Harvard thread (via collaborators)

| File | Paper | Lesson |
|---|---|---|
| `song_2021__general_sum_markov_games.pdf` | Song, Mei, Bai — *When Can We Learn General-Sum Markov Games with a Large Number of Players Sample-Efficiently?*, arXiv 2021 | CCE learnable sample-efficiently in multiplayer games — the multiplayer guarantee |

(Nowak/Fudenberg originals are publisher-paywalled — see
`paywalled_and_books.md`; their results are synthesized in `WHAT_WE_LEARNT.md`.)

### Chinese thread

| File | Paper | Lesson |
|---|---|---|
| `jin_2023__v_learning_decentralized_marl.pdf` | Jin, Liu, Wang, Yu — *V-Learning*, Mathematics of OR 2023 | Decentralized no-regret learners learn Nash/CCE; breaks the curse of multiagency |
| `bai_jin_yu_2020__self_play.pdf` | Bai, Jin, Yu — *Near-Optimal Reinforcement Learning with Self-Play*, NeurIPS 2020 | The self-play precursor: Nash in two-player zero-sum SGs, near-optimally |
| `bai_2022__extensive_form_imperfect_info.pdf` | Bai, Jin, Mei, Yu — *Near-Optimal Learning of Extensive-Form Games with Imperfect Information*, ICML 2022 | The theory reaches game trees — i.e., poker |
| `jin_2022__power_of_exploiter.pdf` | Jin, Liu, Yu — *The Power of Exploiter: Provable Multi-Agent RL in Large State Spaces*, ICML 2022 | Maintaining best-response exploiters is provably the right training/eval structure |
| `xie_2020__suphx.pdf` | Xie et al. (Microsoft) — *Suphx: Mastering Mahjong with Deep RL*, arXiv 2020 | Oracle guiding = train on privileged info, never use it at runtime |
| `zha_2021__douzero.pdf` | Zha et al. — *DouZero: Mastering DouDizhu with Self-Play Deep RL*, ICML 2021 | Plain deep Monte-Carlo self-play scales to hard card games |
| `zha_2020__rlcard.pdf` | Zha et al. — *RLCard: A Toolkit for RL in Card Games*, 2020 | Reference tooling for card-game RL environments |
| `zhao_2024__pokergpt.pdf` | Zhao et al. — *PokerGPT*, arXiv 2024 | LLM as a lightweight multiplayer poker solver — the frontier |
| `xu_2022__autocfr.pdf` | Xu, Li, Fu, Fu, Xing (CASIA/Tsinghua/Tencent) — *AutoCFR*, AAAI 2022 | Meta-learn which CFR variant to use per game — no variant dominates everywhere |

### Russian-school echo (in the poker lineage)

| File | Paper | Lesson |
|---|---|---|
| *(no local PDF)* | Vapnik (VC/SRM), Vovk (aggregating algorithm), Krasovskii–Subbotin, Tsetlin, Petrosyan | Capacity control, defensive calibration, guarantee-first control, tiny learners, time-consistency — synthesized in `WHAT_WE_LEARNT.md`; see `paywalled_and_books.md` |

## Not hosted (paywalled) — see paywalled_and_books.md

Shapley 1953 · Mertens–Neyman 1981 · Pluribus (Science 2019) · Libratus
(Science 2018) · DeepNash (Science 2022) · AlphaHoldem (AAAI 2022; CDN link in
the file) · Fudenberg & Maskin 1986 · Fudenberg & Levine 1998 · Nowak &
Sigmund 1993 · AIVAT (UAI 2018) · Waugh et al. abstraction pathologies (AAMAS
2009) · DBCFR (2012) · Hart & Mas-Colell 2000 · Blackwell 1956 · the books.
