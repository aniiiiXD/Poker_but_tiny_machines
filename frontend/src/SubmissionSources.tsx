import { useEffect, useRef, useState } from "react";
import { api, post, useData, type Data } from "./api";
import { A, Button, Notice } from "./ui";

/** GitHub stores the selected repository and branch; validation happens on Arena. */
function GitHubConnection({ onAccepted, game }: { onAccepted: () => void; game: string }) {
  const config = useData("/github/config");
  const repositories = useData("/github/repositories");
  const [choices, setChoices] = useState<Data[]>([]);
  const [choice, setChoice] = useState("");
  const [branch, setBranch] = useState("");
  const [track, setTrack] = useState("classic");
  const [jobs, setJobs] = useState<Data[]>([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [discovered, setDiscovered] = useState(false);
  const oldStatuses = useRef<Record<string, string>>({});
  const callback = new URLSearchParams(window.location.search).get("github");

  useEffect(() => {
    let cancelled = false;
    api("/github/discovered")
      .then((data) => {
        if (cancelled) return;
        setChoices(data.repositories ?? []);
        setDiscovered(true);
      })
      .catch((e) => {
        // A 404 is normal before the user has authorized repository discovery.
        if (!cancelled && callback === "discovered") setError(e.message);
      });
    return () => { cancelled = true; };
  }, [callback]);

  useEffect(() => {
    let cancelled = false;
    async function loadJobs() {
      try {
        const result = await api("/github/jobs");
        if (cancelled) return;
        const next: Data[] = result.jobs ?? [];
        const completed = next.some((item) =>
          item.status === "completed" && oldStatuses.current[item.id] !== "completed",
        );
        oldStatuses.current = Object.fromEntries(next.map((item) => [item.id, item.status]));
        setJobs(next);
        if (completed) onAccepted();
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Could not load GitHub submissions.");
      }
    }
    void loadJobs();
    const timer = window.setInterval(loadJobs, 4000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [onAccepted]);

  function choose(value: string) {
    setChoice(value);
    const selected = choices.find((repo) => String(repo.repository_id) === value);
    setBranch(selected?.default_branch || "main");
  }
  async function connect() {
    const selected = choices.find((repo) => String(repo.repository_id) === choice);
    if (!selected) return;
    setBusy(true);
    setError("");
    try {
      const result = await post("/github/connect", {
        installation_id: selected.installation_id,
        repository_id: selected.repository_id,
        branch: branch.trim(),
        track,
        game,
      });
      window.location.assign(result.url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not connect the repository.");
      setBusy(false);
    }
  }
  async function sync(id: string) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await post(`/github/repositories/${encodeURIComponent(id)}/sync`);
      setMessage(`Validation queued for commit ${result.commit_sha.slice(0, 7)}.`);
      const resultJobs = await api("/github/jobs");
      setJobs(resultJobs.jobs ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not submit this branch.");
    } finally {
      setBusy(false);
    }
  }
  async function disconnect(id: string) {
    setBusy(true);
    setError("");
    try {
      await api(`/github/repositories/${encodeURIComponent(id)}`, { method: "DELETE" });
      repositories.load();
      setMessage("Repository disconnected. Saved submissions remain available.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not disconnect the repository.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="source-panel" aria-labelledby="github-heading">
      <div className="source-heading">
        <div>
          <p className="source-kicker">Build in your editor</p>
          <h2 id="github-heading">Connect GitHub</h2>
        </div>
        <span className="source-index" aria-hidden="true">01</span>
      </div>
      <p className="muted">Push to a branch and Arena will validate the exact commit for your team.</p>
      {config.data?.configured ? (
        <>
          <div className="source-actions">
            {config.data.install_url && (
              <a className="button ghost" href={config.data.install_url} target="_blank" rel="noreferrer">
                Install GitHub app
              </a>
            )}
            <a className="button ink" href="/api/github/discover">Choose a repository</a>
          </div>
          <p className="source-hint">Install the app on your chosen repositories first, then authorize discovery.</p>
          {callback === "connected" && <p className="success" role="status">Repository connected. Submit its branch below to validate the current commit.</p>}
          {callback === "discovered" && !choices.length && discovered && (
            <p className="source-hint">No repositories found. Install the app on a repository, then choose it again.</p>
          )}
          {choices.length > 0 && (
            <div className="form source-form">
              <label>
                Repository
                <select value={choice} onChange={(e) => choose(e.target.value)}>
                  <option value="">Select a repository</option>
                  {choices.map((repo) => (
                    <option key={`${repo.installation_id}-${repo.repository_id}`} value={repo.repository_id}>
                      {repo.full_name}{repo.private ? " (private)" : ""}
                    </option>
                  ))}
                </select>
              </label>
              <div className="source-fields">
                <label>
                  Branch
                  <input value={branch} onChange={(e) => setBranch(e.target.value)} placeholder="main" maxLength={200} />
                </label>
                <label>
                  Track
                  <select value={track} onChange={(e) => setTrack(e.target.value)}>
                    <option value="classic">Classic bot</option>
                    <option value="model">Model project</option>
                  </select>
                </label>
              </div>
              <Button kind="primary" disabled={busy || !choice || !branch.trim()} onClick={connect}>Connect branch</Button>
            </div>
          )}
          {repositories.data?.repositories?.length > 0 && (
            <div className="source-list">
              <h3>Connected branches</h3>
              {(repositories.data?.repositories ?? []).map((repo: Data) => (
                <div className="source-item" key={repo.id}>
                  <div><strong>{repo.full_name}</strong><small>{repo.branch} · {repo.track === "model" ? "Model" : "Classic"} · {repo.game || "poker"}</small></div>
                  <div className="source-item-actions">
                    <button className="text-button" disabled={busy} onClick={() => sync(repo.id)}>Submit branch</button>
                    <button className="text-button" disabled={busy} onClick={() => disconnect(repo.id)}>Disconnect</button>
                  </div>
                </div>
              ))}
            </div>
          )}
          {jobs.length > 0 && (
            <div className="source-list">
              <h3>Recent validations</h3>
              {jobs.slice(0, 4).map((job) => (
                <div className="source-item" key={job.id}>
                  <div>
                    <strong>{job.repository}</strong>
                    <small>{job.branch} · {job.commit_sha?.slice(0, 7)}</small>
                    {job.error && <small className="source-error">{job.error}</small>}
                  </div>
                  <span className="source-status" role="status">{job.status}</span>
                </div>
              ))}
            </div>
          )}
        </>
      ) : config.error ? (
        <p className="source-hint">GitHub connection is unavailable. You can still use the workshop editor or upload a model.</p>
      ) : config.data ? (
        <p className="source-hint">GitHub connection isn’t configured yet. You can still use the editor or upload a model.</p>
      ) : <p className="source-hint" role="status">Checking GitHub connection…</p>}
      {repositories.error && <Notice error={repositories.error} />}
      <Notice error={error} />
      {message && <p className="success" role="status">{message}</p>}
    </section>
  );
}

function ModelUpload({ onAccepted, game }: { onAccepted: () => void; game: string }) {
  const [name, setName] = useState("My model");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [job, setJob] = useState<Data | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!job?.id || ["completed", "failed"].includes(job.status)) return;
    const jobId: string = job.id;
    let cancelled = false;
    async function poll() {
      try {
        const next = await api(`/jobs/${encodeURIComponent(jobId)}`);
        if (cancelled) return;
        setJob(next);
        if (next.status === "completed") onAccepted();
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Could not load validation status.");
      }
    }
    const timer = window.setInterval(poll, 1500);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [job?.id, job?.status, onAccepted]);

  async function upload() {
    if (!file) return;
    if (file.size > 16_777_216) {
      setError("Project ZIP must be 16 MiB or smaller.");
      return;
    }
    setBusy(true);
    setError("");
    setJob(null);
    try {
      const result = await api(`/models/submissions?name=${encodeURIComponent(name.trim())}&game=${encodeURIComponent(game)}`, {
        method: "POST",
        headers: { "Content-Type": "application/zip" },
        body: file,
      });
      setJob({ id: result.job_id, status: "queued" });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not upload the project.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="source-panel" aria-labelledby="model-heading">
      <div className="source-heading">
        <div>
          <p className="source-kicker">Bring your own model</p>
          <h2 id="model-heading">Upload a project</h2>
        </div>
        <span className="source-index" aria-hidden="true">02</span>
      </div>
      <p className="muted">Submit a ZIP with <code>agent.py</code>, your code and local model weights.</p>
      <a href={`/api/models/starter/download?game=${encodeURIComponent(game)}`} className="text-button source-download">Download model starter ↓</a>
      <p className="source-hint">Python + NumPy · CPU only · 16 MiB ZIP · 512 MB memory · no network.</p>
      <div className="form source-form">
        <label>
          Model name
          <input value={name} maxLength={60} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          Project ZIP
          <input type="file" accept=".zip,application/zip" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <Button kind="primary" disabled={busy || !file || name.trim().length < 2 || Boolean(job && !["completed", "failed"].includes(job.status))} onClick={upload}>
          {busy ? "Uploading…" : "Submit model"}
        </Button>
      </div>
      {job && (
        <div className="source-result" role="status">
          <strong>Validation {job.status}</strong>
          {job.status === "completed" && <span>{job.result?.active ? " Your model is active and ready to practice." : " Accepted. A newer submission is active."}</span>}
          {job.error && <Notice error={job.error} />}
        </div>
      )}
      <Notice error={error} />
    </section>
  );
}

export function SubmissionSources({ me, onAccepted, game = "poker" }: { me: Data | null; onAccepted: () => void; game?: string }) {
  if (!me?.user) {
    return (
      <div className="source-intro">
        <div><p className="source-kicker">Two ways to build</p><h2>Bring your best bot.</h2></div>
        <p>Connect a GitHub branch or upload a model project. <A to="/auth" className="text-button">Sign in to get started</A></p>
      </div>
    );
  }
  if (!me.team) {
    return (
      <div className="source-intro">
        <div><p className="source-kicker">Two ways to build</p><h2>Your team comes first.</h2></div>
        <p>Create or join a team before connecting a branch or uploading a model. <A to="/team" className="text-button">Set up your team</A></p>
      </div>
    );
  }
  return <div className="submission-sources"><GitHubConnection onAccepted={onAccepted} game={game} /><ModelUpload onAccepted={onAccepted} game={game} /></div>;
}
