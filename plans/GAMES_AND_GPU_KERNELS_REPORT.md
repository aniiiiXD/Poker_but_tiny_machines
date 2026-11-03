# Games and GPU kernel challenges for Stack Theory

Status: product research and recommendations, not a list of implemented features. The current engine implements no-limit Texas Hold'em; the other games and all GPU kernels below are proposals.

## Recommended games

| Priority | Game | Why people may care | Engineering considerations |
|---|---|---|---|
| 1 | No-limit Hold'em | Bluffing, uncertainty, replays and a clear flagship | Already implemented. Need many seeded hands, seat rotation, confidence intervals, and budgeted tournaments. |
| 2 | Kuhn and Leduc poker | Small hidden-information games; useful for learning and checking strategies | Cheap to run; clear rules and an easier first challenge. OpenSpiel includes poker variants. |
| 3 | Rock-paper-scissors / iterated matrix games | Very easy first bot, fast feedback, opponent adaptation | Make the interaction repeated; a single round is mostly luck. |
| 4 | Connect Four / chess variants | Easy-to-understand competitive matches and visual replays | Turn timing, legal moves, draws and rating systems. Existing engines may be strong baselines; review rules and licenses. |
| 5 | Negotiation / resource trading | Multi-agent strategy, communication and memorable match stories | Define an explicit protocol, cap messages and execution, and prevent leaking private game state. More engineering than the poker pilot. |

[OpenSpiel's game catalog](https://openspiel.readthedocs.io/en/latest/games.html) is a useful source of candidate environments; verify each game's license, implementation maturity and observation model before adopting it. Use platform-owned game adapters with explicit actions, observations, replay and scoring contracts.

## GPU / ML kernel challenges

These are programming contests for fast, correct GPU kernels, separate from poker agents. Entrants implement a specified operation; official workers compile, check correctness and benchmark on fixed hardware.

| Priority | Kernel | Challenge | Example metrics |
|---|---|---|---|
| 1 | Matrix multiplication / GEMM | Optimize specified shapes and dtypes | Correctness tolerance, median runtime, speed relative to a published baseline |
| 2 | Softmax and layer normalization | Optimize reductions and memory movement | Correctness, latency, bandwidth, performance by shape |
| 3 | Fused attention | Implement a specified attention operation | Correctness, latency and peak memory at multiple sequence lengths |
| 4 | Quantized matrix multiplication | Handle low-bit weights with stated scaling | Error tolerance, throughput and memory use; exact format must be specified |
| 5 | Mixture-of-experts routing / grouped GEMM | Work with variable token and expert workloads | Correctness, tail latency and throughput across balanced and skewed inputs |

Triton publishes tutorials for [matrix multiplication](https://triton-lang.org/main/getting-started/tutorials/03-matrix-multiplication.html) and [fused attention](https://triton-lang.org/main/getting-started/tutorials/). NVIDIA's [CUTLASS documentation](https://docs.nvidia.com/cutlass/latest/) covers GEMM and related operations. These make good educational starting points, not automatically the arena's reference solutions.

## Making a kernel leaderboard trustworthy

- Specify hardware model, driver, runtime/toolchain, shapes, dtypes, numerical tolerances, permitted libraries and benchmark protocol in advance.
- Compile and execute submissions on dedicated ephemeral GPU workers. Never give submissions access to secrets, other contestants' files or private network services.
- Separate correctness from performance; include public examples and hidden validation inputs. Reject wrong results before timing.
- Warm up and measure repeated runs with appropriate GPU synchronization; disclose timing method, aggregation and noise treatment. Check for input-specific shortcuts and benchmark interference.
- Record commit, artifact hash, benchmark version, hardware and environment. Re-run top submissions; keep private tests private without claiming perfect anti-cheat.
- Enforce per-team GPU quotas, queue limits, timeouts and cost budgets. GPU hardware isolation and driver exposure require a specialist review.

## Rollout recommendation

Launch poker and the CPU model track first. Add one educational GPU challenge—GEMM on one fixed GPU type—only after securing GPU worker capacity and a trustworthy correctness/benchmark harness. Follow with attention and quantization if there is demand. Publish baselines and reproducible rules before seeking sponsorship; do not imply any NVIDIA, OpenAI, or other affiliation without agreement.
