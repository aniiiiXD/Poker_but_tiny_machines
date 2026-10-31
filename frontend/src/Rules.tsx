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
      <p className="rules-foot">
        Event settings may differ. Check the event page before joining.
      </p>
    </Page>
  );
}
