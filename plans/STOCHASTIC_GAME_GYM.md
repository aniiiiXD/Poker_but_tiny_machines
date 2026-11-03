# Stack Theory: a gym for AI agents

## Direction

Stack Theory is a place to build and evaluate agents in games with randomness, hidden information, other agents and limited resources. Poker is the first environment, not the definition of the platform. A participant can submit hand-written rules, search, statistical models or trained policies; events declare which runtimes and resources are allowed.

The platform should make each challenge understandable to a beginner while producing reproducible, informative results for experienced researchers. This is a proposed direction: today the working implementation is poker-specific, runs locally and has classic Python and CPU model tracks. Other games, GPU execution and a general-purpose environment API are not implemented.

## What to reuse and what to change

Reuse accounts, teams, GitHub submissions, event scheduling, job management, sandbox execution and results infrastructure where their existing assumptions permit. The current poker engine, `Agent.act` observations, hand logs, replay frames and scoring are poker-specific. Event schemas and UI also encode poker concepts; adapting them requires migrations and compatibility work, not just registering a new game.

Separate three independent choices:

1. **Environment:** the game and its versioned rules, observations and scoring.
2. **Agent runtime:** rules or model code, dependencies, memory and compute limits.
3. **Event:** the environment and runtime versions, competition format, seeds and entry deadlines.

```text
 participant -> submission -> validated artifact ------------------+
                                                                  |
 event -> game + rules + runtime + evaluation protocol             |
                          |                                       |
                          v                                       v
                      scheduler -> isolated runner -> agent processes
                          |              |
                          |              v
                          |       game adapter / engine
                          |              |
                          v              v
                   standings       results + safe replay
```

## Environment contract (proposed)

An environment is trusted platform code, versioned and registered by the platform. Submitted agent code is untrusted and does not run in the engine or API process. The runner coordinates both through a bounded, versioned protocol. A game adapter needs to:

- Create a game from a configuration and private random seed, and initialize the participating seats.
- Identify which agents must act. Support sequential actions and simultaneous decisions; collect simultaneous actions before revealing any of them.
- Produce a separate observation and legal-action specification for each acting agent, without leaking hidden state, future randomness or other agents' private information.
- Validate actions and define a deterministic policy for invalid actions, failures and timeouts. Distinguish agent faults from infrastructure failures so infrastructure faults do not silently count as losses.
- Advance the game, signal termination, and return game-specific scores and metrics.
- Emit versioned events for a replay. Apply game-specific visibility rules before publishing; never publish private state or seeds while they can compromise an active evaluation.

The existing poker `Agent.act(observation)` protocol remains supported. A generic protocol should use an envelope with a protocol version, environment ID and version, agent-facing observation, legal actions, and deadline. The shape of observations and actions is defined by each environment; do not force every game into poker's action names. Agent state and reset boundaries must be explicitly specified per event. Define and test wire schemas before implementation.

The platform should expose an offline development kit for local simulations and baselines. Gymnasium-style compatibility can be an adapter later; no claim of Gymnasium or multi-agent API compatibility should be made until it is built and tested.

## First challenge slate

| Challenge | What agents learn | Randomness / information | Practical first scope |
| --- | --- | --- | --- |
| Poker | Opponent modelling, risk and bluffing | Shuffled cards; private hands | Keep the existing game and established bot contract. |
| Liar's dice | Belief updates, deception and calling bluffs | Private dice rolls | Recommended second game: a small, distinct hidden-information game with a compact replay. |
| Resource allocation | Adaptation, planning and trade-offs | Random demand and supply | Solo or multi-agent simulation; specify reward and episode length before building. |
| Auctions | Bidding under uncertainty and strategic response | Private values and possibly stochastic arrivals | Start with one clearly specified auction format and published baselines. |
| Multi-agent coordination | Cooperation and negotiation under constraints | Randomized maps or events; partial observations | Later: specify communication rules and test collusion assumptions. |

These are candidate games, not existing features. Choose the exact rules and licenses for any third-party implementation before adopting it. The second game should validate that the abstractions work across different observations, actions, scoring and replay formats.

## Model and compute tracks

- **Rules / algorithms:** small code, strict time and memory limits; a good entry point for students.
- **CPU models:** trained weights plus inference code, with bounded artifact size, memory, dependencies and decision time. The existing model track is a starting point, not support for arbitrary frameworks.
- **Open research:** a later, explicitly provisioned track with a published hardware and dependency contract. GPU and larger models require separate infrastructure, budgets and isolation.

Training can happen on the participant's own machine; the first version evaluates submitted inference artifacts. Do not imply that the platform trains models, provides a GPU, permits external model calls or supports every model framework. Each event must state its allowed languages, packages, artifact limits, hardware, network policy and latency budget.

## Evaluation and trust

Publish the game rules, evaluation protocol and baseline implementations before the event. Separate public practice seeds from private held-out evaluation seeds. Run multiple episodes against diverse fixed baselines and, where appropriate, other submissions. Balance positions and random scenarios where possible; report episode count, game-specific score, uncertainty and fault rate rather than only a win percentage. Decide ranking and tie-breaking per event; do not combine incomparable game scores into a single global score without a justified normalization.

Pin the game version, runtime image, submission hash and evaluation configuration for every scored run. Store seeds and full private traces securely for audit; release only material that cannot compromise active evaluations. Include a replay appropriate to each game, and redact private information according to its rules. Evaluate timeout, invalid action, crash and infrastructure-failure handling explicitly. A private seed by itself is not a substitute for a robust anti-leak and anti-cheating design.

## Delivery sequence

1. **Specify the second game:** finalize Liar's dice rules, scoring, observations, action schema, baselines and replay visibility. Preserve existing poker behavior and data.
2. **Extract the minimum common runner:** versioned environment registry and lifecycle; poker adapter; schema and storage changes with backwards compatibility. Add deterministic engine and integration tests.
3. **Build the second adapter:** engine, baseline agents, starter kit, practice flow, game-specific replay and event leaderboard. Test private-state isolation, legal actions and repeated seeded results.
4. **Build the gym experience:** game catalog, challenge pages, runtime constraints, submissions, practice, comparisons and clear metrics. Show only available games and capabilities.
5. **Harden for public use:** isolated worker infrastructure, durable queue, shared storage, quotas, monitoring, secure secrets, backups and abuse testing. See `AWS_VERCEL_ARCHITECTURE.md`; the current local Docker setup is not sufficient for public adversarial code.
6. **Expand thoughtfully:** add environments only when each has a clear task, baselines, scoring, replay, resource contract and maintained evaluation tests. Consider GPU challenges separately after dedicated infrastructure exists.

Success for the first expansion means an existing poker bot and a new dice bot can each be submitted, practiced, evaluated over reproducible episodes and viewed in an appropriate replay, without breaking existing poker events.
