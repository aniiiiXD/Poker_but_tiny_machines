import { A, Page } from "./ui";

const RULES = [
  {
    title: "Build your agent",
    body: [
      <>Submit a Python 3.12 agent with an <code>act(observation)</code> method. Return fold, check, call, or raise; a raise amount is the total contribution for that street. The starter includes a working example, a local simulator, and the interface guide.</>,
    ],
    link: ["/workshop", "Open the workshop →"],
  },
  {
    title: "Equal conditions",
    body: [
      <>Each bot runs in an isolated container without network access, with the same CPU and memory limits. The pilot uses a 1 ms decision cutoff measured inside the container, including operating system scheduling. This is a cutoff, not a hard real-time guarantee.</>,
      <>Invalid actions, errors, or timeouts become a check when legal, otherwise a fold; the fault is recorded and shown in practice results.</>,
    ],
  },
  {
    title: "Play the table",
    body: [
      <>Tables usually seat eight bots. Blinds start at 10/20 and double every 25 hands. At the hand cap, remaining places are settled with independent chip model (ICM) equity. The founding event runs six rounds, eight tables per round, up to 50 hands per table; each event page shows its exact configuration.</>,
    ],
  },
  {
    title: "Score the rounds",
    body: [
      <>Finishing places award 8, 5, 3, 2, 1, 0, 0, 0 points. A round score is the mean points per table, weighted by its round number, so later rounds count more. Equal totals share a rank. Baseline copies can fill empty seats without scoring.</>,
      <>No cash prizes are configured for the local pilot. Chips are simulated; the competition is code.</>,
    ],
  },
];

const BLUFF_RULES = [
  {
    title: "Bluff · Stack Theory v1",
    body: [
      <>A selected variant of the classic Cheat / I Doubt It party game — not the only official ruleset. Four seats, a standard 52-card deck, 13 cards each. The required rank starts at Ace and advances one step per batch: A, 2, 3 … K, then A again.</>,
    ],
  },
  {
    title: "Claim and challenge",
    body: [
      <>On your turn, place 1–4 face-down cards and claim they are all the required rank. Lying is allowed. Every other player then decides clockwise, starting with the next seat: challenge or pass. The first challenge stops the sequence; if everyone passes, the play stays face down.</>,
      <>A challenge reveals only the challenged batch. If any card differs from the claim, the claimant takes the whole pile; otherwise the challenger does. Older pile cards stay hidden.</>,
    ],
  },
  {
    title: "Win and score",
    body: [
      <>After every resolution the rank advances and play passes to the seat after the claimant. Emptying your hand wins only once all challenge decisions have resolved — and only if your hand is still empty. A match ends after 500 decisions at most; then the fewest cards wins and ties share the point.</>,
      <>Scoring: a win is worth 1, a loss 0; an event standing is your average match score. Invalid actions or timeouts are faults and fall back to a legal move (your sorted-lowest card, or pass).</>,
    ],
  },
  {
    title: "What your bot sees",
    body: [
      <>Only public information and your own hand: card counts, declared ranks, challenge decisions that already happened, and revealed challenged batches. Never the deck order, opponent hands, or face-down pile. The starter kit in the Workshop has a working example.</>,
    ],
    link: ["/workshop?game=bluff", "Build a Bluff bot →"],
  },
];

export function Rules() {
  return (
    <Page
      eyebrow="The guide"
      title="How the arena works"
      lead="The rules, constraints, and scoring behind the current pilot."
    >
      <div className="rules-grid">
        {RULES.map((rule, i) => (
          <article key={rule.title}>
            <span className="rule-num">RULE {String(i + 1).padStart(2, "0")}</span>
            <h2>{rule.title}</h2>
            {rule.body.map((para, j) => (
              <p key={j}>{para}</p>
            ))}
            {rule.link && (
              <p style={{ marginTop: 10 }}>
                <A to={rule.link[0]} className="text-button">
                  {rule.link[1]}
                </A>
              </p>
            )}
          </article>
        ))}
      </div>
      <h2 className="display-2" style={{ margin: "48px 0 20px" }}>
        Bluff · the second arena
      </h2>
      <div className="rules-grid">
        {BLUFF_RULES.map((rule) => (
          <article key={rule.title}>
            <h2>{rule.title}</h2>
            {rule.body.map((para, j) => (
              <p key={j}>{para}</p>
            ))}
            {rule.link && (
              <p style={{ marginTop: 10 }}>
                <A to={rule.link[0]} className="text-button">
                  {rule.link[1]}
                </A>
              </p>
            )}
          </article>
        ))}
      </div>
      <p className="rules-foot">
        Event settings may differ. Check the event page before joining.
      </p>
    </Page>
  );
}
