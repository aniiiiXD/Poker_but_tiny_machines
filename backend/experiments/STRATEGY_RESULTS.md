# Aggression and random bluff strategy

The bot is `aggression_bluff_bot.py`. It evaluates the best made hand from its hole cards and the board, plays two pair carefully against repeated or large raises, and plays three of a kind or better aggressively. It sometimes bluffs or makes a random 50/50 guess about an opponent's bluff; that guess is not an observation of their cards. It also uses basic preflop selection, bet size, pot odds and a flush-draw heuristic.

## Comparison

Run on October 31, 2026 with the project's PokerKit engine:

```sh
cd backend
uv run python experiments/compare_strategy.py --tables 128 --hands 50 --seed 5202601
```

Each strategy played 128 eight-player tables against seven of the eight built-in baselines. The omitted baseline and candidate seat were balanced, with matching seeds and seating for the three comparisons. Each player started with 2,000 chips. The tournament uses 8/5/3/2/1/0/0/0 points and ICM to award remaining points at the hand cap.

| Strategy | Mean tournament points | Standard error | Mean ending chips | Chip leader |
|---|---:|---:|---:|---:|
| Proposed strategy | 4.554 | 0.098 | 1,951 | 1/128 |
| Same rules without random bluffing or guessing | 4.560 | 0.098 | 1,954 | 1/128 |
| Existing starter bot | 3.332 | 0.283 | 4,054 | 28/128 |

The proposed strategy scored 1.222 more points per table than the starter on these paired games (paired standard error 0.295). The point difference versus the same rules with random decisions disabled was -0.005 (paired standard error 0.002): the 50/50 guesses did not demonstrate a useful gain here. Across all tables, no agent faults were recorded.

These opponents are simple in-repository bots, not Sequoia bots or strong human players. This is not evidence of profitability in a real-money game. The cautious strategy generally preserved a modest stack and collected tournament points, whereas the starter led more tables and accumulated more chips on average. Those are different objectives; an improvement in this tournament's ICM score does not establish that the proposed strategy is stronger for cash games or stronger opposition.

A separate four-table execution through the actual Docker sandbox, using a 1 ms decision limit and a 30-hand cap, produced zero bot faults. This is a small runtime check, not a guarantee against timeouts under load. The code has unit tests in `tests/test_proposed_strategy.py`.

## Sandbox timing and action history

An additional run used 16 real Docker-sandbox tables, 50 hands each (800 hands total), with seed `20261101`:

```sh
uv run python experiments/measure_strategy.py --tables 16 --hands 50 --seed 20261101
```

The bot returned 1,024 timed decisions with zero recorded faults. Mean: 0.0539 ms; median: 0.0509 ms; p95: 0.0758 ms; p99: 0.1053 ms; maximum: 0.2832 ms. These wall-clock measurements were taken by the sandbox supervisor and include worker scheduling and JSON parsing/serialization; they exclude host-to-container transport and simulator processing. They reflect this local machine and load, not Sequoia's timing environment. Only completed decisions are included in the latency statistics; this run had no faults or timeouts.

| Decision time (ms) | Decisions |
|---|---:|
| 0.000–0.025 | 0 |
| 0.025–0.050 | 460 |
| 0.050–0.100 | 546 |
| 0.100–0.250 | 17 |
| 0.250–0.500 | 1 |
| 0.500–1.000 | 0 |

Action history for these 1,024 decisions: 668 folds, 221 checks, 23 calls and 112 raises. Of the decisions, 781 were preflop, 95 on the flop, 74 on the turn and 74 on the river. All comparisons use the arena's own simple baseline bots, not Sequoia tournament bots.

A separate 30-hand practice replay was saved locally as `5070b85037564a00af77159e8eb2818f`; open it at http://127.0.0.1:8001/replays/5070b85037564a00af77159e8eb2818f while the local arena is running.
