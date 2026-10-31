import { useEffect, useState } from "react";
import { post, useData, type Data } from "./api";
import { A, Button, Notice, Page, Status, fmtDay, fmtLong } from "./ui";

export function Events() {
  const { data, error } = useData("/events");
  const events = data?.events ?? [];
  return (
    <Page
      title="Find your table"
      lead="Build with your team and compete in a Campus Arena event."
      eyebrow="Events"
    >
      <Notice error={error} />
      {!data && !error && <p role="status">Loading events…</p>}
      {data && events.length === 0 && (
        <div className="empty">No events yet. Check back for the next table.</div>
      )}
      {data && events.length > 0 && (
        <div className="rows">
          {events.map((e: Data) => (
            <A key={e.id} to={"/events/" + e.id} className="row-item">
              <span className="grow">
                <h3>
                  {e.title}
                  <span className="arrow">↗</span>
                </h3>
                <p className="muted" style={{ marginTop: 4, maxWidth: "60ch" }}>
                  {e.description}
                </p>
              </span>
              <Status text={e.exhibition ? "Exhibition" : e.status} done={e.status === "completed"} />
              <span className="meta">
                {fmtDay(e.build_starts_at)} · {e.entry_count} teams · {e.round_count} rounds
              </span>
            </A>
          ))}
        </div>
      )}
    </Page>
  );
}

function Countdown({ target }: { target: string }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 60000);
    return () => window.clearInterval(timer);
  }, []);
  const minutes = Math.max(0, Math.ceil((new Date(target).getTime() - now) / 60000));
  return (
    <span>
      {minutes
        ? `Starts in ${Math.floor(minutes / 1440)}d ${Math.floor((minutes % 1440) / 60)}h ${minutes % 60}m`
        : "Build start time reached"}
    </span>
  );
}

export function EventDetail({
  id,
  refresh,
}: {
  id: string;
  refresh: () => void;
}) {
  const { data, error, load } = useData("/events/" + id);
  const [err, setErr] = useState(""),
    [busy, setBusy] = useState(false);
  if (!data)
    return (
      <Page title="Event" eyebrow="Events">
        <Notice error={error} />
        {!error && <p role="status">Loading event…</p>}
      </Page>
    );
  const e = data.event;
  const facts: [string, string][] = [
    ["Build starts", fmtLong(e.build_starts_at)],
    ["Build ends", fmtLong(e.build_ends_at)],
    ["Round interval", Math.round(e.round_interval_seconds / 60) + " min"],
    ["Maximum hands", String(e.max_hands)],
    ["Game", e.variant],
    ["Rounds", String(e.round_count)],
    ["Decision time", e.decision_ms + " ms"],
    ["Tables per round", String(e.tables_per_round)],
    ["Partner", e.sponsor_name || "Open to partners"],
  ];
  return (
    <Page title={e.title} lead={e.description} eyebrow="Event">
      <div className="grid-2">
        <div>
          <div className="panel">
            <div style={{ display: "flex", gap: 20, alignItems: "baseline", flexWrap: "wrap" }}>
              <Status
                text={e.exhibition ? "Exhibition" : e.status}
                done={e.status === "completed"}
              />
              <span className="muted">{e.entry_count} teams entered</span>
            </div>
            <h2 style={{ margin: "12px 0 8px" }}>Bring your best bot</h2>
            <p className="muted">
              Join with your team, then submit a bot before the round begins.
              Each table plays at most {e.max_hands} hands.
            </p>
            <div style={{ marginTop: 18 }}>
              <Button
                kind="primary"
                disabled={busy || e.joined || e.status === "completed" || e.exhibition}
                onClick={() => {
                  setBusy(true);
                  post("/events/" + id + "/join")
                    .then(() => {
                      load();
                      refresh();
                    })
                    .catch((x) => setErr(x.message))
                    .finally(() => setBusy(false));
                }}
              >
                {e.exhibition || e.status === "completed"
                  ? "Event closed"
                  : e.joined
                    ? "Your team has joined"
                    : busy
                      ? "Joining…"
                      : "Join this event"}
              </Button>
            </div>
            <div style={{ marginTop: 12 }}>
              <Notice error={err} />
            </div>
          </div>

          <h2 className="display-2" style={{ margin: "40px 0 16px" }}>
            Rounds
          </h2>
          {data.rounds.length ? (
            <div className="rows">
              {data.rounds.map((r: Data) => (
                <div className="row-item" key={r.id}>
                  <span className="grow">
                    <h3>Round {r.number}</h3>
                  </span>
                  <Status text={r.status} done={r.status === "completed"} />
                </div>
              ))}
            </div>
          ) : (
            <div className="empty">Rounds will appear when scheduled.</div>
          )}

          <h2 className="display-2" style={{ margin: "40px 0 16px" }}>
            Leaderboard
          </h2>
          <LeaderboardTable rows={data.leaderboard} />
        </div>

        <aside className="panel facts">
          <h3 style={{ marginBottom: 14 }}>Event details</h3>
          {e.status === "registration" && (
            <p className="status-line" style={{ marginBottom: 10 }}>
              <Countdown target={e.build_starts_at} />
            </p>
          )}
          {facts.map(([label, value]) => (
            <p className="fact" key={label}>
              <span>{label}</span>
              <b>{value}</b>
            </p>
          ))}
        </aside>
      </div>
    </Page>
  );
}

export function LeaderboardTable({ rows }: { rows: Data[] }) {
  return rows?.length ? (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>#</th>
            <th>Team</th>
            <th>College</th>
            <th className="num">Points</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r: Data, i: number) => (
            <tr key={i}>
              <td className="rank-cell">{r.rank}</td>
              <td>
                <b>{r.team_name}</b>
                {r.is_baseline && <small>baseline</small>}
              </td>
              <td>{r.college || "—"}</td>
              <td className="num">{r.total_score}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  ) : (
    <div className="empty">No scores yet. Results will appear after a round.</div>
  );
}

export function Leaderboard() {
  const { data, error } = useData("/leaderboard");
  return (
    <Page
      title="The standings"
      lead="Mean points per table, weighted by round. Equal totals share a rank."
      eyebrow="Standings"
    >
      <Notice error={error} />
      {data ? (
        <LeaderboardTable rows={data.leaderboard} />
      ) : (
        !error && <p role="status">Loading standings…</p>
      )}
    </Page>
  );
}

export function Replays() {
  const { data, error } = useData("/replays");
  const replays = data?.replays ?? [];
  return (
    <Page
      title="Watch the hands unfold"
      lead="Replay completed games, one decision at a time."
      eyebrow="Replays"
    >
      <Notice error={error} />
      {!data && !error && <p role="status">Loading replays…</p>}
      {data && replays.length === 0 && (
        <div className="empty">
          No completed replays yet. Run a practice game in the workshop to make one.
        </div>
      )}
      {data && replays.length > 0 && (
        <div className="rows">
          {replays.map((r: Data) => (
            <A key={r.id} to={"/replays/" + r.id} className="row-item">
              <span className="grow">
                <h3>
                  {r.title}
                  <span className="arrow">↗</span>
                </h3>
              </span>
              <Status text={r.source} done={r.source === "practice"} />
              <span className="meta">
                {r.hand_count} hands · {fmtDay(r.created_at)}
              </span>
            </A>
          ))}
        </div>
      )}
    </Page>
  );
}
