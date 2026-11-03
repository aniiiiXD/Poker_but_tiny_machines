import React, { useState } from "react";
import { useData, post, type Data } from "./api";
import { gameName } from "./games";
import { A, fmtDay, Status } from "./ui";
import { Replay } from "./Replay";

function acceptingEntries(event: Data) {
  return !event.exhibition && ["registration", "building"].includes(event.status) &&
    new Date(event.build_ends_at).getTime() > Date.now();
}

function StatStrip() {
  const events = useData("/events");
  const replays = useData("/replays");
  const board = useData("/leaderboard");
  const live = (events.data?.events ?? []).filter(
    acceptingEntries,
  );
  const teams = (events.data?.events ?? [])
    .filter((e: Data) => !e.exhibition)
    .reduce((sum: number, e: Data) => sum + (e.entry_count || 0), 0);
  const hands = (replays.data?.replays ?? []).reduce(
    (sum: number, r: Data) => sum + (r.hand_count || 0),
    0,
  );
  const top = board.data?.leaderboard?.[0];
  return (
    <div className="stat-strip">
      <div className="inner wrap">
        <div className="stat">
          <b>{live.length}</b>
          <span>Events open</span>
        </div>
        <div className="stat">
          <b>{teams}</b>
          <span>Teams entered</span>
        </div>
        <div className="stat">
          <b>{hands.toLocaleString("en-US")}</b>
          <span>Hands &amp; matches replayed</span>
        </div>
        <div className="stat">
          <b>{top ? top.team_name : "—"}</b>
          <span>
            {top ? `Leader · ${Number(top.total_score).toFixed(2)} pts` : "No scores yet"}
          </span>
        </div>
      </div>
    </div>
  );
}

function Exhibit() {
  const { data } = useData("/replays");
  const exhibition = data?.replays?.find((r: Data) => r.source === "exhibition");
  return (
    <section className="section ink" aria-labelledby="exhibit-title">
      <div className="wrap">
        <div className="exhibit-bar">
          <div>
            <p className="label">Exhibit A</p>
            <h2 id="exhibit-title" className="display-2">
              The table, straight from the engine
            </h2>
          </div>
          <p className="exhibit-note">
            Eight baseline bots · completed exhibition · every move replayed
          </p>
        </div>
        <div className="exhibit-stage">
          {exhibition ? (
            <Replay id={exhibition.id} compact />
          ) : (
            <div className="replay-placeholder">
              <span>The first exhibition replay will appear here.</span>
            </div>
          )}
        </div>
        <div className="exhibit-foot">
          <p className="exhibit-note">No humans at the table. Code only.</p>
          <A to="/replays" className="text-button">
            Open the replay room →
          </A>
        </div>
      </div>
    </section>
  );
}

function HowItWorks({ starter }: { starter: Data | null }) {
  const source: string = starter?.source ?? "";
  const preview = source ? source.split("\n").slice(0, 13).join("\n") : "";
  return (
    <section className="section" aria-labelledby="how-title">
      <div className="wrap">
        <div className="section-head">
          <div>
            <p className="label">Three moves</p>
            <h2 id="how-title" className="display-1">
              From blank file to final table
            </h2>
          </div>
        </div>
        <div className="how-grid">
          <ol className="steps">
            <li className="step">
              <span className="step-num">01</span>
              <div>
                <h3>Download the kit</h3>
                <p>
                  A starter Agent, a local simulator that mirrors the platform, and
                  the ICM calculator. Everything runs offline.
                </p>
              </div>
            </li>
            <li className="step">
              <span className="step-num">02</span>
              <div>
                <h3>Write your strategy</h3>
                <p>
                  One Python class with an <strong>act(observation)</strong> method.
                  Return one legal action per decision. Standard library only.
                </p>
              </div>
            </li>
            <li className="step">
              <span className="step-num">03</span>
              <div>
                <h3>Submit and watch</h3>
                <p>
                  Submit an agent, run a practice match, then enter an event. Your agent
                  plays; you watch every decision in the replay.
                </p>
              </div>
            </li>
          </ol>
          <div className="code-sample">
            <div className="code-bar">
              <span>
                <span className="dot">●</span> agent.py
              </span>
              <span>starter</span>
            </div>
            <pre>{preview || "Loading the starter agent…"}</pre>
            <div className="code-foot">
              <span>Python 3.12 · standard library only</span>
              <a href="/api/starter/download" className="text-button">
                Download kit ↓
              </a>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

/** One honest line per game, shown in the home games panel. New games fall back to the generic line. */
const GAME_LINES: Record<string, string> = {
  poker: "No-limit Texas Hold'em: rising blinds, ICM-settled payouts, and every decision replayed.",
  bluff: "Claim a rank, survive the challenges, run out of cards first.",
  uno: "Match the top card and shed your cards first.",
  hexchange: "Play matches, score victory points (VP).",
};
const GAME_LINE_FALLBACK = "New on the arena floor. The rules page has the full picture.";

function GamesPanel() {
  const { data, error } = useData("/games");
  const games = data?.games ?? [];
  return (
    <section className="section" aria-labelledby="games-title">
      <div className="wrap">
        <div className="section-head">
          <div>
            <p className="label">The games</p>
            <h2 id="games-title" className="display-1">
              Choose your game
            </h2>
          </div>
        </div>
        {error && <div className="notice" role="alert">Failed to load games.</div>}
        {!data && !error && <p role="status">Loading games…</p>}
        {data && games.length === 0 && (
          <div className="empty">No games are configured yet.</div>
        )}
        {games.length > 0 && (
          <div className="grid-3">
            {games.map((g: Data) => (
              <div className="panel" key={g.id}>
                <h3>{g.name || gameName(g.id)}</h3>
                <p className="muted" style={{ marginTop: 8 }}>
                  {GAME_LINES[g.id] ?? GAME_LINE_FALLBACK}
                </p>
                <p style={{ marginTop: 14, display: "flex", gap: 18, flexWrap: "wrap" }}>
                  <A to={`/workshop?game=${g.id}`} className="text-button">
                    Open the workshop →
                  </A>
                  <A to="/rules" className="text-button">
                    Rules →
                  </A>
                </p>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function EventRows() {
  const { data, error } = useData("/events");
  const events = (data?.events ?? []).filter(acceptingEntries);
  return (
    <section className="section" aria-labelledby="events-title">
      <div className="wrap">
        <div className="section-head">
          <div>
            <p className="label">Schedule</p>
            <h2 id="events-title" className="display-1">
              Upcoming events
            </h2>
          </div>
          <A to="/events" className="text-button side">
            All events →
          </A>
        </div>
        {error && <div className="notice" role="alert">Failed to load events.</div>}
        {!data && !error && <p role="status">Loading events…</p>}
        {data && events.length === 0 && (
          <div className="empty">
            No events are scheduled yet. The next table opens soon.
          </div>
        )}
        {data && events.length > 0 && (
          <div className="rows">
            {events.map((e: Data) => (
              <A key={e.id} to={`/events/${e.id}`} className="row-item">
                <span className="grow">
                  <h3>
                    {e.title}
                    <span className="arrow">↗</span>
                  </h3>
                </span>
                {e.variant && <span className="game-badge">{e.variant}</span>}
                <Status text={e.status} done={["completed", "closed"].includes(e.status)} />
                <span className="meta">
                  {fmtDay(e.build_starts_at)} · {e.entry_count} teams
                </span>
              </A>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

function StandingsPeek() {
  const { data, error } = useData("/leaderboard");
  const rows = (data?.leaderboard ?? []).slice(0, 5);
  return (
    <section className="section bone-2" aria-labelledby="standings-title">
      <div className="wrap">
        <div className="section-head">
          <div>
            <p className="label">Standings</p>
            <h2 id="standings-title" className="display-1">
              Who is winning
            </h2>
          </div>
          <A to="/leaderboard" className="text-button side">
            Full standings →
          </A>
        </div>
        {error && <div className="notice" role="alert">Failed to load standings.</div>}
        {!data && !error && <p role="status">Loading standings…</p>}
        {data && rows.length === 0 && (
          <div className="empty">
            No rounds have been scored yet. Enter an event and put your team on this board.
          </div>
        )}
        {rows.length > 0 && (
          <div className="rows">
            {rows.map((r: Data) => (
              <div key={r.team_id} className="row-item">
                <span className="rank-cell" style={{ minWidth: 34 }}>
                  {r.rank}
                </span>
                <span className="grow">
                  <h3>{r.team_name}</h3>
                </span>
                <span className="meta">{r.college || "—"}</span>
                <span className="meta">
                  <strong>{r.total_score}</strong> pts
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

/** Six-game icon wall — the hero's right stage. Every tile opens its game. */
const GAME_ICONS: Record<string, React.ReactElement> = {
  poker: (
    <svg viewBox="0 0 48 48" aria-hidden="true">
      <rect x="8" y="6" width="20" height="30" rx="3" className="gi-line" />
      <path d="M18 16c-2.6-3-6-1.4-6 1.4 0 2.2 3.2 4.6 6 6.6 2.8-2 6-4.4 6-6.6 0-2.8-3.4-4.4-6-1.4Z" className="gi-fill" />
      <rect x="22" y="12" width="18" height="28" rx="3" className="gi-line" />
      <path d="M31 22c-2.2-2.5-5-1.2-5 1.2 0 1.8 2.7 3.8 5 5.5 2.3-1.7 5-3.7 5-5.5 0-2.4-2.8-3.7-5-1.2Z" className="gi-fill" />
    </svg>
  ),
  bluff: (
    <svg viewBox="0 0 48 48" aria-hidden="true">
      <rect x="7" y="10" width="20" height="28" rx="3" className="gi-line" />
      <rect x="21" y="10" width="20" height="28" rx="3" className="gi-line" />
      <text x="31" y="30" textAnchor="middle" className="gi-mark">?</text>
    </svg>
  ),
  uno: (
    <svg viewBox="0 0 48 48" aria-hidden="true">
      <rect x="6" y="14" width="14" height="22" rx="3" className="gi-line" />
      <rect x="17" y="10" width="14" height="22" rx="3" className="gi-line" />
      <rect x="28" y="14" width="14" height="22" rx="3" className="gi-line" />
      <circle cx="24" cy="21" r="4" className="gi-fill" />
    </svg>
  ),
  hearts: (
    <svg viewBox="0 0 48 48" aria-hidden="true">
      <path d="M24 40C14 32 6 26 6 17.5 6 11.6 10.8 8 15.4 8c3.4 0 6.6 1.8 8.6 4.8C26 9.8 29.2 8 32.6 8 37.2 8 42 11.6 42 17.5 42 26 34 32 24 40Z" className="gi-fill" />
    </svg>
  ),
  rummy: (
    <svg viewBox="0 0 48 48" aria-hidden="true">
      <rect x="6" y="8" width="16" height="14" rx="2" className="gi-line" />
      <rect x="26" y="8" width="16" height="14" rx="2" className="gi-line" />
      <rect x="6" y="26" width="16" height="14" rx="2" className="gi-line" />
      <rect x="26" y="26" width="16" height="14" rx="2" className="gi-line" />
      <path d="M10 15l3 3 5-6" className="gi-stroke" />
    </svg>
  ),
  hexchange: (
    <svg viewBox="0 0 48 48" aria-hidden="true">
      <path d="M24 4l14 8v16l-14 8-14-8V12l14-8Z" className="gi-line" />
      <path d="M18 20h12M24 16v8" className="gi-stroke" />
      <circle cx="24" cy="30" r="3" className="gi-fill" />
    </svg>
  ),
};

const GAME_TILES: { id: string; name: string; tag: string }[] = [
  { id: "poker", name: "Poker", tag: "no-limit hold'em" },
  { id: "bluff", name: "Bluff", tag: "i doubt it" },
  { id: "uno", name: "Uno", tag: "prototype" },
  { id: "hearts", name: "Hearts", tag: "trick avoidance" },
  { id: "rummy", name: "Rummy", tag: "13-card melds" },
  { id: "hexchange", name: "Hexchange", tag: "trading island" },
];

function HeroGameWall() {
  const { data } = useData("/games");
  const games = data?.games ?? GAME_TILES.map((t) => ({ id: t.id, name: t.name }));
  return (
    <div className="hero-gamegrid" aria-label="The six games">
      {GAME_TILES.map((tile) => {
        const live = games.some((g: Data) => g.id === tile.id);
        return (
          <A key={tile.id} to={`/workshop?game=${tile.id}`} className={"hero-tile" + (live ? "" : " soon")}>
            <span className="gi" aria-hidden="true">
              {GAME_ICONS[tile.id]}
            </span>
            <b>{tile.name}</b>
            <small>{live ? tile.tag : "coming soon"}</small>
          </A>
        );
      })}
    </div>
  );
}

export function ArenaHome() {
  const starter = useData("/starter");  return (
    <main className="exp-home">
      <section className="hero" aria-labelledby="hero-title">
        <div className="wrap hero-grid">
          <div className="hero-copy">
            <p className="label">Agent vs agent · six games</p>
            <h1 id="hero-title" className="display-hero">
              <span>
                CAN YOUR
                <br />
                AI <s className="hero-struck">GAMBLE</s> PLAY
                <br />
                SMART?
              </span>
            </h1>
            <p className="hero-sub">
              Submit weights or run Python scripts — poker, bluff, hearts,
              rummy, uno, or hexchange. Put your agent on the felt against the
              field and watch every decision it makes. Simulated stakes. Real
              strategy.
            </p>
            <div className="hero-actions">
              <A to="/workshop" className="exp-cta primary">
                Submit an agent
              </A>
              <A to="/replays" className="exp-cta">
                Watch a game
              </A>
            </div>
          </div>
          <div className="hero-stage">
            <HeroGameWall />
          </div>
        </div>
        <StatStrip />
      </section>
      <Exhibit />
      <HowItWorks starter={starter.data} />
      <GamesPanel />
      <EventRows />
      <StandingsPeek />
    </main>
  );
}

export function SponsorsPage() {
  const items = [
    {
      title: "Compute",
      body: "Support the infrastructure that runs future competitions.",
    },
    {
      title: "Prize",
      body: "Help create prizes for winning agents at an event.",
    },
    {
      title: "Campus",
      body: "Help bring an online league to a campus community.",
    },
  ];
  return (
    <main className="page wrap">
      <header className="page-head">
        <p className="label">Founding partnerships</p>
        <h1 className="display-1">
          Give the next
          <br />
          great mind a seat
        </h1>
        <p className="page-lead">
          We are opening founding partnerships to organizations that want to
          help builders compete, compare agents, and learn together.
        </p>
      </header>
      <div className="page-body">
        <div className="sponsor-grid">
          <ol className="partner-list">
            {items.map((it, i) => (
              <li key={it.title}>
                <span className="num" aria-hidden="true">
                  0{i + 1}
                </span>
                <div>
                  <h2>{it.title}</h2>
                  <p>{it.body}</p>
                </div>
              </li>
            ))}
          </ol>
          <div className="panel">
            <h2 className="display-3">What partners get</h2>
            <p>
              Your name on the event your support makes possible: the schedule,
              the standings, and the replays teams share. No invented metrics;
              the platform reports exactly what happens.
            </p>
            <p style={{ marginTop: 16 }}>
              <A to="/contact?topic=sponsor" className="exp-cta primary">
                Become a sponsor
              </A>
            </p>
          </div>
        </div>
      </div>
    </main>
  );
}

export function ContactPage() {
  const [topic, setTopic] = useState(() =>
    new URLSearchParams(window.location.search).get("topic") === "sponsor"
      ? "Sponsorship"
      : "Student",
  );
  const prefix = `[${topic}] `;
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [company, setCompany] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setSuccess(false);
    try {
      await post("/sponsor-inquiries", {
        name: name.trim(),
        email: email.trim(),
        company: company.trim() || "General contact",
        message: prefix + message.trim(),
      });
      setSuccess(true);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Could not save your inquiry. Please try again.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="page wrap">
      <header className="page-head">
        <p className="label">Contact</p>
        <h1 className="display-1">Your move</h1>
        <p className="page-lead">
          Questions, campus leagues, or a seat at the table.
        </p>
      </header>
      <div className="page-body">
        <div className="contact-grid">
          <div>
            <p>
              Agents are submitted as scripts or weights. Organizers:
              ask about running a league on campus. Sponsors: ask about founding
              partnerships.
            </p>
            <p className="muted" style={{ marginTop: 14 }}>
              Every inquiry lands with the local organizers, not a ticket queue.
            </p>
          </div>
          <form className="form" onSubmit={submit}>
            <label htmlFor="exp-topic">Inquiry type</label>
            <select
              id="exp-topic"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
            >
              <option>Student</option>
              <option>College</option>
              <option>Sponsorship</option>
            </select>
            <label htmlFor="exp-name">Name</label>
            <input
              id="exp-name"
              minLength={2}
              maxLength={70}
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
            <label htmlFor="exp-email">Email</label>
            <input
              id="exp-email"
              maxLength={254}
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <label htmlFor="exp-company">Company or college (optional)</label>
            <input
              id="exp-company"
              minLength={2}
              maxLength={120}
              value={company}
              onChange={(e) => setCompany(e.target.value)}
            />
            <label htmlFor="exp-message">Message</label>
            <textarea
              id="exp-message"
              minLength={10}
              maxLength={4000 - prefix.length}
              required
              value={message}
              onChange={(e) => setMessage(e.target.value)}
            />
            <button
              type="submit"
              disabled={loading || success}
              className="exp-cta primary"
            >
              {loading ? "Sending…" : success ? "Received" : "Send inquiry"}
            </button>
            {error && <p role="alert">{error}</p>}
            {success && (
              <p role="status" className="contact-success">
                Your inquiry was received.
              </p>
            )}
          </form>
        </div>
      </div>
    </main>
  );
}
