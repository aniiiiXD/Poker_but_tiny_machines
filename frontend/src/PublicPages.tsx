import { useEffect, useState } from "react";
import { post, useData, type Data } from "./api";
import { gameCapLabel, gameName, gameUnit, unitCount } from "./games";
import { A, Button, Notice, Page, Status, fmtDay, fmtLong } from "./ui";

/** Friendly labels for keys in the detail endpoint's game rules object. */
const RULE_LABELS: Record<string, string> = {
  language: "Language",
  source_limit_bytes: "Source limit",
  project_limit_bytes: "Project limit",
  submission_cooldown_seconds: "Submission cooldown",
  initial_chips: "Starting chips",
  blinds: "Blinds",
  payouts: "Payouts",
  scoring: "Scoring",
  tie_policy: "Ties",
  network_access: "Network access",
  decision_cap: "Decision cap",
  rank_cycle: "Rank cycle",
  matches: "Matches",
};
// Already shown as event facts, or internal bookkeeping.
const RULE_SKIP = new Set(["track", "game", "game_id", "rules_version", "decision_ms", "sandbox_digest"]);

function formatBytes(n: number): string {
  if (n >= 1024 * 1024) return `${Math.round(n / (1024 * 1024))} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

/** Turn the game-specific rules object into fact rows. Keys may be absent; unknown keys render with a humanized label. */
function ruleRows(rules: Data | undefined): [string, string][] {
  if (!rules || typeof rules !== "object" || Array.isArray(rules)) return [];
  const rows: [string, string][] = [];
  for (const [key, value] of Object.entries(rules)) {
    if (RULE_SKIP.has(key) || value === null || value === undefined || value === "") continue;
    if (typeof value === "boolean") rows.push([RULE_LABELS[key] ?? humanize(key), value ? "Yes" : "No"]);
    else if (typeof value === "number")
      rows.push([RULE_LABELS[key] ?? humanize(key), key.endsWith("_bytes") ? formatBytes(value) : String(value)]);
    else if (Array.isArray(value) && value.every((v) => typeof v !== "object"))
      rows.push([RULE_LABELS[key] ?? humanize(key), value.map(String).join(", ")]);
    else if (typeof value === "string") rows.push([RULE_LABELS[key] ?? humanize(key), value]);
  }
  return rows;
}

function humanize(key: string): string {
  const words = key.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function Events() {
  const { data, error } = useData("/events");
  const events = data?.events ?? [];
  return (
    <Page
      title="Find your table"
      lead="Build with your team and compete in a Stack Theory event."
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
              {e.variant && <span className="game-badge">{e.variant}</span>}
              <Status text={e.exhibition ? "Exhibition" : e.status} done={["completed", "closed"].includes(e.status)} />
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
  const gameId = e.game || e.game_id || "poker";
  const unit = gameUnit(gameId);
  const closed = e.exhibition || ["completed", "closed"].includes(e.status);
  const canJoin = ["registration", "building"].includes(e.status) &&
    new Date(e.build_ends_at).getTime() > Date.now();
  const capCopy =
    e.max_hands !== undefined && e.max_hands !== null
      ? ` Each table plays at most ${e.max_hands} ${unit}.`
      : "";
  const facts: [string, string][] = [
    ["Build starts", fmtLong(e.build_starts_at)],
    ["Build ends", fmtLong(e.build_ends_at)],
    ["Round interval", Math.round(e.round_interval_seconds / 60) + " min"],
    [gameCapLabel(gameId), String(e.max_hands)],
    ["Game", e.variant || gameName(gameId)],
    ["Bot track", e.track === "model" ? "Model project" : "Classic bot"],
    ["Rounds", String(e.round_count)],
    ["Decision time", e.decision_ms + " ms"],
    ["Tables per round", String(e.tables_per_round)],
    ["Partner", e.sponsor_name || "Open to partners"],
  ];
  const rules = ruleRows(data.rules);
  return (
    <Page title={e.title} lead={e.description} eyebrow="Event">
      <div className="grid-2">
        <div>
          <div className="panel">
            <div style={{ display: "flex", gap: 20, alignItems: "baseline", flexWrap: "wrap" }}>
              <Status
                text={e.exhibition ? "Exhibition" : e.status}
                done={closed}
              />
              <span className="muted">{e.entry_count} teams entered</span>
            </div>
            <h2 style={{ margin: "12px 0 8px" }}>{closed ? "This event has closed" : "Bring your best bot"}</h2>
            <p className="muted">
              {closed
                ? "Registration has ended. Check the schedule for the next event."
                : `Join with your team, then submit a bot before the round begins.${capCopy}`}
            </p>
            <div style={{ marginTop: 18 }}>
              <Button
                kind="primary"
                disabled={busy || e.joined || closed || !canJoin}
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
                {closed || !canJoin
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
            <div className="empty">{closed ? "No rounds were played." : "Rounds will appear when scheduled."}</div>
          )}

          <h2 className="display-2" style={{ margin: "40px 0 16px" }}>
            Leaderboard
          </h2>
          <LeaderboardTable rows={data.leaderboard} game={gameId} />
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
          {rules.length > 0 && (
            <>
              <h3 style={{ margin: "22px 0 4px" }}>Game rules</h3>
              {rules.map(([label, value]) => (
                <p className="fact" key={label}>
                  <span>{label}</span>
                  <b>{value}</b>
                </p>
              ))}
            </>
          )}
        </aside>
      </div>
    </Page>
  );
}

export function LeaderboardTable({ rows, game }: { rows: Data[]; game?: string }) {
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
    <div className="empty">
      {game && game !== "poker"
        ? `No ${gameName(game)} rounds scored yet. The floor is open.`
        : "No scores yet. Results will appear after a round."}
    </div>
  );
}

export function Leaderboard() {
  const games = useData("/games");
  const [game, setGame] = useState(
    () => new URLSearchParams(location.search).get("game") || "poker",
  );
  useEffect(() => {
    const url = new URL(location.href);
    url.searchParams.set("game", game);
    history.replaceState(null, "", url);
  }, [game]);
  const { data, error } = useData(`/leaderboard?game=${game}`);
  const tabs = games.data?.games ?? [];
  return (
    <Page
      title="The standings"
      lead={
        game === "poker"
          ? "Mean points per table, weighted by round. Equal totals share a rank."
          : "Updated as rounds complete. Equal totals share a rank."
      }
      eyebrow="Standings"
    >
      {tabs.length > 0 && (
        <div className="game-tabs" role="tablist" aria-label="Game">
          {tabs.map((g: Data) => (
            <button
              key={g.id}
              role="tab"
              aria-selected={game === g.id}
              className={"game-tab" + (game === g.id ? " on" : "")}
              onClick={() => setGame(g.id)}
            >
              {g.name || gameName(g.id)}
            </button>
          ))}
        </div>
      )}
      <Notice error={error} />
      {data ? (
        <LeaderboardTable rows={data.leaderboard} game={game} />
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
      title="Watch the games unfold"
      lead="Replay a completed game, one decision at a time."
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
                {unitCount(r.hand_count, r.game)} · {fmtDay(r.created_at)}
              </span>
            </A>
          ))}
        </div>
      )}
    </Page>
  );
}
