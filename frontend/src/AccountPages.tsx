import { useEffect, useState } from "react";
import { post, useData, type Data } from "./api";
import { A, Notice, Page, go } from "./ui";

export function Auth({ refresh }: { refresh: () => void }) {
  const [register, setRegister] = useState(true),
    [form, setForm] = useState({
      name: "",
      email: "",
      password: "",
      college: "",
    }),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [sent, setSent] = useState(false);
  return (
    <Page
      title={register ? "Join the arena" : "Welcome back"}
      lead="Your team, your bot, your next move."
      eyebrow="Account"
    >
      <div className="auth-wrap">
        {sent ? (
          <div className="panel form">
            <h2 className="display-3">Check your inbox</h2>
            <p className="muted">
              We sent a verification link to {form.email}. Verify, then submit your
              first bot. Didn't get it? The banner on any page can resend it.
            </p>
          </div>
        ) : (
        <form
          className="form panel"
          onSubmit={(e) => {
            e.preventDefault();
            setBusy(true);
            post("/auth/" + (register ? "register" : "login"), form)
              .then((r) => {
                if (register && r.verification !== "smtp") setSent(true);
                refresh();
                if (!register) go("/profile");
              })
              .catch((x) => setError(x.message))
              .finally(() => setBusy(false));
          }}
        >
          {register && (
            <>
              <label>
                Name
                <input
                  required
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                />
              </label>
              <label>
                College
                <input
                  required
                  value={form.college}
                  onChange={(e) => setForm({ ...form, college: e.target.value })}
                />
              </label>
            </>
          )}
          <label>
            Email
            <input
              type="email"
              required
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
            />
          </label>
          <label>
            Password
            <input
              type="password"
              minLength={register ? 8 : undefined}
              required
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
            />
          </label>
          <Notice error={error} />
          <button className="button primary" disabled={busy} type="submit">
            {busy ? "Please wait…" : register ? "Create account" : "Log in"}
          </button>
          <button
            type="button"
            className="text-button"
            onClick={() => {
              setRegister(!register);
              setError("");
            }}
          >
            {register
              ? "Already have an account? Log in"
              : "New here? Create an account"}
          </button>
          {!register && (
            <A to="/forgot" className="text-button">
              Forgot your password?
            </A>
          )}
        </form>
        )}
      </div>
    </Page>
  );
}

export function VerifyPage() {
  const token = new URLSearchParams(window.location.search).get("token") || "";
  const [state, setState] = useState<"working" | "done" | "failed">(token ? "working" : "failed");
  useEffect(() => {
    if (!token) return;
    post("/auth/verify", { token })
      .then(() => setState("done"))
      .catch(() => setState("failed"));
  }, [token]);
  return (
    <Page title="Email verification" eyebrow="Account">
      {state === "working" && <p role="status">Checking your link…</p>}
      {state === "done" && (
        <div className="panel form" style={{ maxWidth: 460 }}>
          <h2 className="display-3">Verified</h2>
          <p className="muted">You can submit bots from the workshop now.</p>
          <A to="/workshop" className="exp-cta primary">
            Go to the workshop
          </A>
        </div>
      )}
      {state === "failed" && (
        <div className="panel form" style={{ maxWidth: 460 }}>
          <h2 className="display-3">Link invalid</h2>
          <p className="muted">
            The link is missing, expired, or already used. Log in and resend the
            verification email from the banner.
          </p>
          <A to="/auth" className="text-button">
            Back to log in →
          </A>
        </div>
      )}
    </Page>
  );
}

export function ForgotPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  return (
    <Page title="Password reset" lead="We send a reset link if the address is registered." eyebrow="Account">
      <div className="auth-wrap">
        {sent ? (
          <div className="panel form">
            <h2 className="display-3">Link sent</h2>
            <p className="muted">
              If {email} belongs to an account, a reset link is on its way. It
              expires in one hour.
            </p>
          </div>
        ) : (
          <form
            className="form panel"
            onSubmit={(e) => {
              e.preventDefault();
              post("/auth/forgot", { email })
                .then(() => setSent(true))
                .catch((x) => setError(x.message));
            }}
          >
            <label>
              Email
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </label>
            <Notice error={error} />
            <button className="button primary" type="submit">
              Send reset link
            </button>
            <A to="/auth" className="text-button">
              Back to log in →
            </A>
          </form>
        )}
      </div>
    </Page>
  );
}

export function ResetPage() {
  const token = new URLSearchParams(window.location.search).get("token") || "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  return (
    <Page title="Set a new password" eyebrow="Account">
      <div className="auth-wrap">
        {done ? (
          <div className="panel form">
            <h2 className="display-3">Password updated</h2>
            <p className="muted">All old sessions were signed out. Log in with the new password.</p>
            <A to="/auth" className="exp-cta primary">
              Log in
            </A>
          </div>
        ) : (
          <form
            className="form panel"
            onSubmit={(e) => {
              e.preventDefault();
              if (password !== confirm) {
                setError("The two passwords do not match.");
                return;
              }
              post("/auth/reset", { token, password })
                .then(() => setDone(true))
                .catch((x) => setError(x.message));
            }}
          >
            <label>
              New password
              <input
                type="password"
                minLength={8}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </label>
            <label>
              Repeat new password
              <input
                type="password"
                minLength={8}
                required
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
              />
            </label>
            <Notice error={error} />
            <button className="button primary" type="submit" disabled={!token}>
              Set password
            </button>
            {!token && <p className="muted">Open this page from the reset email link.</p>}
          </form>
        )}
      </div>
    </Page>
  );
}

export function Team({
  me,
  refresh,
}: {
  me: Data | null;
  refresh: () => void;
}) {
  const [name, setName] = useState(""),
    [code, setCode] = useState(""),
    [error, setError] = useState("");
  if (!me?.user)
    return (
      <Page title="Your team" eyebrow="Team">
        <p>Log in to create or join a team.</p>
        <p style={{ marginTop: 16 }}>
          <A to="/auth" className="exp-cta primary">
            Log in or sign up
          </A>
        </p>
      </Page>
    );
  return (
    <Page title="Your team" lead="Build together. Compete together." eyebrow="Team">
      <Notice error={error} />
      {me.team ? (
        <div className="panel" style={{ maxWidth: 560 }}>
          <p className="label">Your team</p>
          <h2 className="display-2" style={{ margin: "8px 0 12px" }}>
            {me.team.name}
          </h2>
          <p className="muted">Share this code with your teammate:</p>
          <p className="join-code" aria-label="Invitation code">
            {me.team.join_code}
          </p>
          <h3 style={{ margin: "18px 0 4px" }}>Members</h3>
          {me.team.members.map((m: Data) => (
            <div className="list-row" key={m.id}>
              {m.name}
            </div>
          ))}
        </div>
      ) : (
        <div className="grid-2">
          <form
            className="panel form"
            onSubmit={(e) => {
              e.preventDefault();
              post("/team", { name })
                .then(refresh)
                .catch((x) => setError(x.message));
            }}
          >
            <h2 className="display-3">Create a team</h2>
            <p className="muted">Start a team and invite others with your code.</p>
            <label>
              Team name
              <input
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <button className="button primary" type="submit">
              Create team
            </button>
          </form>
          <form
            className="panel form"
            onSubmit={(e) => {
              e.preventDefault();
              post("/team/join", { code })
                .then(refresh)
                .catch((x) => setError(x.message));
            }}
          >
            <h2 className="display-3">Join a team</h2>
            <p className="muted">Have an invitation? Enter the team code.</p>
            <label>
              Join code
              <input
                required
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
            </label>
            <button className="button ink" type="submit">
              Join team
            </button>
          </form>
        </div>
      )}
    </Page>
  );
}

export function Profile({
  me,
  refresh,
}: {
  me: Data | null;
  refresh: () => void;
}) {
  const { data, error } = useData("/profile");
  if (!me?.user)
    return (
      <Page title="Your profile" eyebrow="Account">
        <p>Log in to see your profile.</p>
        <p style={{ marginTop: 16 }}>
          <A to="/auth" className="exp-cta primary">
            Log in or sign up
          </A>
        </p>
      </Page>
    );
  const statLabels: Record<string, string> = {
    submissions: "Submissions",
    practice_runs: "Practice runs",
    events: "Events",
  };
  return (
    <Page title={me.user.name} lead={me.user.college} eyebrow="Profile">
      <Notice error={error} />
      <div className="grid-2">
        <div className="panel">
          <h2 className="display-3">Your arena</h2>
          <p className="muted">{me.user.email}</p>
          <p style={{ marginTop: 6 }}>
            Team: {me.team?.name || "Not on a team yet"}
          </p>
          <p style={{ marginTop: 10 }}>
            <A to="/team" className="text-button">
              Manage team →
            </A>
          </p>
          {data && (
            <div className="stats">
              {Object.entries(data.stats).map(([k, v]) => (
                <div key={k}>
                  <b>{String(v)}</b>
                  <span>{statLabels[k] || k.replace("_", " ")}</span>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="panel">
          <h2 className="display-3">Recent submissions</h2>
          {data?.recent_submissions?.length ? (
            data.recent_submissions.map((s: Data) => (
              <div className="list-row" key={s.id}>
                <b>{s.name}</b>
                <span className="muted">{s.status}</span>
              </div>
            ))
          ) : (
            <p className="muted">No submissions yet.</p>
          )}
          <p style={{ marginTop: 14 }}>
            <A to="/workshop" className="text-button">
              Go to workshop →
            </A>
          </p>
        </div>
      </div>
      <button
        className="text-button logout"
        onClick={() =>
          post("/auth/logout")
            .then(() => {
              refresh();
              go("/");
            })
            .catch((e) => alert(e.message))
        }
      >
        Log out
      </button>
    </Page>
  );
}
