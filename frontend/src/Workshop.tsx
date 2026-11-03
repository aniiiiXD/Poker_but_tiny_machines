import { useEffect, useRef, useState } from "react";
import { api, post, useData, type Data } from "./api";
import { gameName } from "./games";
import { A, Button, Notice, Page } from "./ui";
import { SubmissionSources } from "./SubmissionSources";

type Draft = { game: string; source: string | null; name: string };

function readDraft(game: string): Draft {
  const source = localStorage.getItem(`arena-draft-source-${game}`) ??
    (game === "poker" ? localStorage.getItem("arena-draft-source") : null);
  const name = localStorage.getItem(`arena-draft-name-${game}`) ??
    (game === "poker" ? localStorage.getItem("arena-draft-name") : null) ?? "My bot";
  return { game, source, name };
}

function CodeEditor({
  source,
  onChange,
  dirty,
}: {
  source: string;
  onChange: (next: string) => void;
  dirty: string;
}) {
  const areaRef = useRef<HTMLTextAreaElement>(null);
  const gutterRef = useRef<HTMLDivElement>(null);
  const lines = Math.max(source.split("\n").length, 24);
  const sync = () => {
    if (gutterRef.current && areaRef.current)
      gutterRef.current.scrollTop = areaRef.current.scrollTop;
  };
  useEffect(sync, [source]);
  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key !== "Tab") return;
    e.preventDefault();
    const area = e.currentTarget;
    const start = area.selectionStart;
    const next = source.slice(0, start) + "    " + source.slice(area.selectionEnd);
    onChange(next);
    requestAnimationFrame(() => {
      area.selectionStart = area.selectionEnd = start + 4;
    });
  }
  return (
    <div className="editor">
      <div className="editor-bar">
        <span>
          <span className="dot">●</span> agent.py
        </span>
        <span>{dirty}</span>
      </div>
      <div className="editor-body">
        <div className="gutter" ref={gutterRef} aria-hidden="true">
          {Array.from({ length: lines }, (_, i) => i + 1).join("\n")}
        </div>
        <textarea
          ref={areaRef}
          spellCheck={false}
          wrap="off"
          aria-label="Bot Python source"
          value={source}
          onScroll={sync}
          onKeyDown={handleKeyDown}
          onChange={(e) => onChange(e.target.value)}
        />
      </div>
    </div>
  );
}

export function Workshop({ me }: { me: Data | null }) {
  const games = useData("/games");
  const [game, setGame] = useState(
    () => new URLSearchParams(location.search).get("game") || "poker",
  );
  const starter = useData(`/starter?game=${game}`),
    subs = useData("/submissions");
  const [draft, setDraft] = useState<Draft>(() => readDraft(game)),
    [error, setError] = useState(""),
    [success, setSuccess] = useState(""),
    [job, setJob] = useState<Data | null>(null),
    [busy, setBusy] = useState(false);
  const isBluff = game === "bluff";
  const source = draft.game === game ? (draft.source ?? "") : "";
  const name = draft.game === game ? draft.name : "My bot";
  const setSource = (next: string) => setDraft((current) => ({ ...current, source: next }));
  const setName = (next: string) => setDraft((current) => ({ ...current, name: next }));
  useEffect(() => {
    const url = new URL(location.href);
    url.searchParams.set("game", game);
    history.replaceState(null, "", url);
  }, [game]);
  useEffect(() => {
    // Do not hydrate from the previous game's still-in-flight starter response.
    if (starter.data?.game !== game || typeof starter.data?.source !== "string") return;
    const initialSource = starter.data.source as string;
    setDraft((current) => current.game === game && current.source === null
      ? { ...current, source: initialSource } : current);
  }, [game, starter.data]);
  useEffect(() => {
    if (draft.game !== game || draft.source === null) return;
    localStorage.setItem(`arena-draft-source-${game}`, draft.source);
    localStorage.setItem(`arena-draft-name-${game}`, draft.name);
  }, [draft, game]);
  useEffect(() => {
    if (!job?.id || ["completed", "failed"].includes(job.status)) return;
    let cancelled = false;
    const timer = setInterval(() => {
      api("/jobs/" + job.id)
        .then((result) => {
          if (!cancelled) setJob(result);
        })
        .catch((e) => {
          if (!cancelled) setError(e.message);
        });
    }, 1000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [job?.id, job?.status]);
  const active = subs.data?.submissions?.find(
    (s: Data) => s.active && s.game === game,
  );
  const cooldown = subs.data?.cooldown_remaining ?? 0;
  function practice(custom: boolean) {
    setError("");
    setBusy(true);
    const body = custom
      ? { submission_id: active.id, game }
      : { game };
    if (isBluff) (body as Data).matches = 1;
    else (body as Data).hands = 20;
    post("/practice", body)
      .then((r) => setJob({ id: r.job_id, status: "queued", progress: 0 }))
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  }
  function save() {
    setBusy(true);
    setError("");
    setSuccess("");
    post("/submissions", { name, source, game })
      .then(() => {
        setSuccess("Bot saved and active. The next round uses this bot.");
        subs.load();
      })
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  }
  const dirty =
    active && source === active.source && name === active.name
      ? "Matches active bot"
      : "Unsaved draft";
  const running = !!job && !["completed", "failed"].includes(job.status);
  return (
    <Page
      title="The agent workshop"
      lead="Write a strategy or load your weights, submit, and see how it plays."
      eyebrow="Build"
    >
      <SubmissionSources me={me} onAccepted={subs.load} game={game} />
      <div className="game-tabs" role="tablist" aria-label="Game">
        {(games.data?.games || []).map((g: Data) => (
          <button
            key={g.id}
            role="tab"
            aria-selected={game === g.id}
            className={"game-tab" + (game === g.id ? " on" : "")}
            onClick={() => {
              setDraft(readDraft(g.id));
              setGame(g.id);
              setJob(null);
              setError("");
              setSuccess("");
            }}
          >
            {g.name}
          </button>
        ))}
      </div>
      <div className="workshop-grid">
        <div>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "baseline",
              gap: 16,
              marginBottom: 14,
              flexWrap: "wrap",
            }}
          >
            <h2 className="display-2">Make your move</h2>
            <a href={`/api/starter/download?game=${game}`} className="text-button">
              Download starter ↓
            </a>
          </div>
          <CodeEditor source={source} onChange={setSource} dirty={dirty} />
          <div className="editor-actions">
            <label className="field">
              Agent name
              <input value={name} onChange={(e) => setName(e.target.value)} maxLength={60} />
            </label>
            <Button
              kind="primary"
              disabled={busy || !source.trim() || !name.trim()}
              onClick={save}
            >
              {busy ? "Saving…" : "Save submission"}
            </Button>
          </div>
          {cooldown > 0 && !error && (
            <p className="cooldown" role="status" style={{ marginTop: 10 }}>
              One submission every five minutes. Next submission in {cooldown}s.
            </p>
          )}
          <div style={{ marginTop: 12 }}>
            <Notice error={error} />
            {success && <div className="success">{success}</div>}
          </div>
        </div>

        <aside className="stack">
          <div className="panel">
            <h3 className="display-3">Practice table</h3>
            <p className="muted" style={{ marginTop: 6 }}>
              {isBluff
                ? "Play one full Bluff match against three built-in strategies and inspect every decision in the replay."
                : game === "poker"
                  ? "Run 20 hands and inspect every decision in the replay."
                  : "Run a practice game against built-in strategies and inspect every decision in the replay."}
            </p>
            <div className="stack" style={{ marginTop: 14 }}>
              <Button
                kind="primary"
                disabled={busy || !active || running}
                onClick={() => practice(true)}
              >
                Practice with my bot
              </Button>
              <Button disabled={busy || running} onClick={() => practice(false)}>
                Try baseline demo
              </Button>
            </div>
            <p className="muted" style={{ marginTop: 12, fontSize: 13.5 }}>
              {active
                ? `Active bot: ${active.name}`
                : !me?.user
                  ? "Log in and submit an agent to practice with it. The baseline demo works without an account."
                  : "Submit an agent to practice with it. Custom bots need a team and the sandbox running."}
            </p>
            {job && (
              <div className="job">
                <b style={{ textTransform: "capitalize" }}>Practice {job.status}</b>
                <div className="progress" aria-hidden="true">
                  <i style={{ width: `${job.progress}%` }} />
                </div>
                {job.error && <Notice error={job.error} />}
                {job.result && (
                  <>
                    <p className="muted" style={{ fontSize: 14 }}>
                      {job.result.matches
                        ? `${job.result.matches} match${job.result.matches === 1 ? "" : "es"}`
                        : `${job.result.hands} hands`}{" "}
                      ·{" "}
                      {job.result.scores.reduce(
                        (total: number, score: Data) => total + score.faults,
                        0,
                      )}{" "}
                      faults total
                    </p>
                    <div className="practice-scores" aria-label="Practice results">
                      {job.result.scores.map((score: Data, i: number) => (
                        <div key={i}>
                          <strong>{score.name}</strong>
                          <span>
                            {score.points} pts
                            {score.chips !== undefined ? ` · ${score.chips} chips` : ""} ·{" "}
                            {score.faults} faults
                            {score.error ? ` · ${score.error}` : ""}
                          </span>
                        </div>
                      ))}
                    </div>
                    <p className="fault-note">
                      Faults include errors, timeouts, and illegal actions; the
                      engine falls back to a legal{" "}
                      {game === "poker" ? "check or fold" : "play or pass"}.
                    </p>
                    <A className="text-button" to={"/replays/" + job.result.replay_id}>
                      Open replay →
                    </A>
                  </>
                )}
              </div>
            )}
          </div>

          <div className="panel">
            <h3 className="display-3">Interface</h3>
            <p className="muted" style={{ marginTop: 6 }}>
              Your agent receives an observation and returns one action per
              decision.
            </p>
            <details style={{ marginTop: 10 }}>
              <summary>Interface &amp; guide</summary>
              <pre>
                {starter.data?.interface}
                {"\n\n"}
                {starter.data?.guide}
              </pre>
            </details>
          </div>

          <div className="panel">
            <h3 className="display-3">Saved agents</h3>
            {!me?.user ? (
              <p className="muted" style={{ marginTop: 6 }}>
                Log in to save your agent.
              </p>
            ) : subs.data?.submissions?.filter((s: Data) => s.game === game).length ? (
              <div style={{ marginTop: 6 }}>
                {subs.data.submissions
                  .filter((s: Data) => s.game === game)
                  .map((s: Data) => (
                    <div className="list-row" key={s.id}>
                      <span>
                        {s.name} {s.active ? <small>active</small> : null}
                        <small> {s.track === "model" ? "model" : "classic"} · {s.status}</small>
                        {s.github_commit && <small> · {s.github_commit.slice(0, 7)}</small>}
                      </span>
                      {s.track !== "model" && (
                        <button
                          className="text-button"
                          onClick={() => {
                            setSource(s.source);
                            setName(s.name);
                          }}
                        >
                          Load
                        </button>
                      )}
                    </div>
                  ))}
              </div>
            ) : (
              <p className="muted" style={{ marginTop: 6 }}>
                No {gameName(game)} submissions yet.
              </p>
            )}
          </div>
        </aside>
      </div>
    </Page>
  );
}
