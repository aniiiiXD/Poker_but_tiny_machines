# Stochastic games for Stack Theory

Research shortlist, 1 November 2026. These are candidates; only poker is currently implemented in Stack Theory. Effort estimates are rough product-integration judgments, not benchmarks. New games all require generalizing the existing poker-specific runner, event model and replays. Review dependency licenses, assets, variants and obligations individually before reuse.

## Updated direction: familiar social games

The user clarified that the priority is recognizable, fun games people already play, especially **Bluff (Cheat / I Doubt It)** and **UNO**. The research-benchmark shortlist below is secondary to this direction.

1. **Bluff:** players put cards face down, announce a rank and can be challenged. Multiple rule variants exist, so specify one before building. [Bicycle rules](https://bicyclecards.com/how-to-play/i-doubt-it/).
2. **UNO:** players race to empty their hand using matching cards and action cards. [Mattel rules](https://service.mattel.com/instruction_sheets/10020-SN70_G1_4XN_IS_Uno.pdf). Check rights and permissions for commercial use of names, artwork and branded content; a separate original card game is an alternative.
3. **Crazy Eights:** a recognizable shedding game and possible alternative foundation; OpenSpiel lists an implementation, marked lightly tested. It is not an UNO implementation. [OpenSpiel catalogue](https://github.com/google-deepmind/open_spiel/blob/master/docs/games.md).
4. **Rummy / Gin Rummy, Hearts and Spades:** familiar card games with shuffled hidden hands, different set-building or trick-taking decisions, and existing rules to pin. OpenSpiel includes Gin Rummy and Hearts; check the selected Spades implementation separately.
5. **Liar's Dice:** social bluffing using private dice; distinct from the card game Bluff.
6. **CATAN and Risk:** engaging longer-term choices involving dice, negotiation or territorial tactics, with substantially more complex engines and visualizations. Check licensing, trademarks and art rights before using branded material. [CATAN rules](https://www.catan.com/sites/default/files/2025-03/CN3081%20CATAN%E2%80%93The%20Game%20Rulebook%20secure%20%281%29.pdf), [Risk game](https://instructions.hasbro.com/en-gb/instruction/risk-game).

Possible original social game: **Double Trouble**, a draft shedding game where players discard face-down cards while making a claim, opponents may challenge, and a limited set of action cards can change the turn order or force a draw. This is a concept combining familiar mechanisms, not a verified novel invention. Specify claim rules, challenge priority, action effects and a game-ending condition, then playtest before implementation.

## Candidates

| Game | Chance and hidden information | What it tests | Approximate effort | Why consider it |
| --- | --- | --- | --- | --- |
| Liar's Dice | Private random dice; escalating claims | Beliefs, bluffing, opponent adaptation | Low–medium | Compact, understandable, strong poker-adjacent first addition. |
| Goofspiel | Random prize-card order in the chosen variant; simultaneous secret bids | Auction strategy, resource conservation, prediction | Low–medium | Easy to visualize; simultaneous actions exercise the proposed runner. |
| Backgammon | Public dice rolls; board is visible | Search, probability, long-term risk | Medium | Familiar, spectator-friendly and a classic AI challenge. |
| Hanabi | Shuffled cards; players see teammates' hands but not their own | Cooperation, communication and reasoning about others | Medium–high | A research benchmark; evaluation must mix unfamiliar partners, not only identical self-play. |
| Hearts | Random card deal; hidden hands | Inference, risk and multi-player tactics | Medium | Easy-to-follow card game; full rules and scoring must be pinned. |
| Yacht | Dice rolls | Risk, planning and resource allocation | Low–medium | Simple baseline; primarily a scoring challenge rather than direct interaction. |
| Bargaining with random private valuations | Randomly assigned hidden values | Negotiation and strategic compromise | Medium | Supports competition and cooperation; specify permitted messages and binding agreements. |
| Lux AI Season 3 | Randomized game mechanics and maps; fog of war | Adaptation, exploration and multi-agent planning | High | Strong advanced/research challenge; substantially more compute, dependencies and visualization work. |
| FrozenLake | Chance of slipping in the configured stochastic variant | Basic navigation and RL | Low–medium | Beginner training and tutorial benchmark, not inherently a competitive multiplayer game. |

Sources: [OpenSpiel game catalogue](https://github.com/google-deepmind/open_spiel/blob/master/docs/games.md) documents Goofspiel, Backgammon, Hanabi, Hearts, Yacht and bargaining; [OpenSpiel paper](https://arxiv.org/html/1908.09453v6) includes Liar's Dice; [Hanabi research paper](https://arxiv.org/abs/1902.00506) describes cooperative imperfect-information research; [Lux AI Season 3 specification](https://github.com/Lux-AI-Challenge/Lux-Design-S3/blob/main/docs/specs.md) describes randomized mechanics and fog of war; [Gymnasium FrozenLake](https://gymnasium.farama.org/environments/toy_text/frozen_lake/) describes slippery dynamics.

OpenSpiel provides a useful research environment and API covering multiple game types, with an [Apache-2.0 repository license](https://github.com/google-deepmind/open_spiel). It is not a turnkey Stack Theory tournament service or a security sandbox. Game support, optional dependencies, variants and test maturity differ by game; assess each before integrating. [Lux AI Season 3](https://github.com/Lux-AI-Challenge/Lux-Design-S3) is also Apache-2.0 at repository level; review dependencies and assets separately.

## Original proposal: Signal & Scarcity

A proposed Stack Theory game about allocating scarce compute under uncertain demand. It combines well-known mechanisms; this particular combination is a concept, not a claim of novelty or a verified unique invention.

**Pitch:** four agents bid for limited compute capacity while seeing different noisy signals about future job demand. They must choose when to spend and whether to trust their forecasts. All currency and workloads are simulated.

### Draft playable rules

- Four players, ten rounds. Each starts with 100 credits. The publicly known fixed total server capacity is six compute units per round; unused units do not carry over.
- At the start of each round, the engine independently draws each player's private demand as an integer in 0–4 from a published distribution. Each player sees their own noisy demand signal, derived from their demand using a published noise model. No player sees another player's demand, signal or bid.
- Players simultaneously submit an integer unit bid from 0–10 credits. Their bid must be affordable for at most four units: `4 × bid <= current credits`. A zero bid requests no units. All positive bids request up to four identical units.
- Rank all requested units by bid, highest first. Allocate the six units in that order; for equal bids use a seeded random tie-break that is independent of player identity. Each player pays their own bid for each unit actually allocated. No player can spend more than their balance. Unit bids and aggregate allocation are revealed after the round; private demand and signals remain private until the evaluation is safe to disclose.
- Each allocated unit serves one unit of that player's demand, up to its demand; extra units are wasted. Score each round as `10 × served demand − credits paid − 2 × unmet demand`. The match score is the sum over all ten rounds; highest score wins, with ties shared. Credits carry over, and unused credits have no end-of-game score.
- The engine draws all chance, never the bot. Invalid actions and timeouts have a published fallback and fault count; infrastructure failures void or retry the episode rather than silently penalizing the agent.

Example: an agent has demand 3, bids 4 and receives 2 units. It pays 8 credits, serves 2, leaves 1 unmet and scores `20 − 8 − 2 = 10` for the round. Its demand is visible to the reader here only to explain the arithmetic; in the game the agent sees a noisy signal.

The exact distributions, number of units, payoff constants and disclosure rules are initial design choices requiring simulation and balancing. This is a sealed-bid allocation game; it does not yet include trading, resource price prediction claims or a GPU infrastructure simulation.

### Evaluation and replay

Publish the exact distribution, rules, fixed baselines and public practice seeds; reserve separate private seeds for evaluation. Rotate seat assignments, randomize seeded tie-breaks, and evaluate many episodes against diverse fixed bots and varied fields. Report average match score with an uncertainty interval, win/draw rate, demand served, wasted capacity and fault rate. An offline replay can show demand after results are released; live observations must not reveal private information.

Start with simple fixed-bid, signal-threshold and budget-aware baselines; tune only against practice scenarios. Verify that the same engine version, seeds, agents and action sequence reproduce outcomes. Change rules and version IDs together. Test whether a trivial always-zero or always-max strategy dominates before announcing a competition.

## Recommended sequence

1. Preserve poker and extract a minimal, versioned game interface.
2. Add Liar's Dice, with a starter bot, safe replay and baseline comparisons.
3. Add Goofspiel to exercise simultaneous action collection and sealed bids.
4. Prototype Signal & Scarcity offline; run balance experiments before making any research or fairness claims.
5. Add cooperative Hanabi or an advanced environment such as Lux only after selecting evaluation rules, checking compatibility and budgeting infrastructure.

See `STOCHASTIC_GAME_GYM.md` for the shared runner, model tracks and public-launch requirements.
