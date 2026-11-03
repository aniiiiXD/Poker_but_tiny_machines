import React, { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, post, type Data } from "./api";
import { A } from "./ui";
import { Replay } from "./Replay";
import { Events, EventDetail, Leaderboard, Replays } from "./PublicPages";
import { Auth, Team, Profile, VerifyPage, ForgotPage, ResetPage } from "./AccountPages";
import { ArenaHome, SponsorsPage, ContactPage } from "./Experience";
import { Workshop } from "./Workshop";
import "./arena.css";
import { Rules } from "./Rules";

const TOOLS: [string, string][] = [
  ["/workshop", "Workshop"],
  ["/events", "Events"],
  ["/replays", "Replays"],
  ["/leaderboard", "Standings"],
  ["/team", "Team"],
  ["/rules", "Rules"],
];

function Brand() {
  return (
    <A to="/" className="brand">
      <span className="brand-mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none">
          <path d="M4 7.5 12 4l8 3.5-8 3.5-8-3.5Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
          <path d="m4 11 8 3.5 8-3.5M4 14.5l8 3.5 8-3.5M4 18l8 3.5 8-3.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
      <span>Stack Theory</span>
    </A>
  );
}

function VerifyBanner({ me }: { me: Data | null }) {
  const [state, setState] = useState("");
  if (!me?.user || me.user.email_verified) return null;
  return (
    <div className="verify-banner" role="status">
      <span>
        Verify your email to submit bots. The link went to{" "}
        <b>{me.user.email}</b>.
      </span>
      <button
        className="text-button"
        onClick={() => {
          post("/auth/verify/resend")
            .then(() => setState("Sent. Check the inbox (and spam)."))
            .catch((e) => setState(e.message));
        }}
      >
        Resend link
      </button>
      {state && <small>{state}</small>}
    </div>
  );
}

function App() {
  const [path, setPath] = useState(location.pathname),
    [me, setMe] = useState<Data | null>(null);
  const refresh = useCallback(() => {
    api("/me")
      .then(setMe)
      .catch(() => setMe(null));
  }, []);
  useEffect(() => {
    refresh();
    const h = () => setPath(location.pathname);
    addEventListener("popstate", h);
    return () => removeEventListener("popstate", h);
  }, [refresh]);

  let view: React.ReactNode;
  if (path === "/" || path === "/arena") view = <ArenaHome />;
  else if (path === "/events") view = <Events />;
  else if (path.startsWith("/events/"))
    view = <EventDetail id={path.split("/")[2]} refresh={refresh} />;
  else if (path === "/workshop") view = <Workshop me={me} />;
  else if (path === "/leaderboard") view = <Leaderboard />;
  else if (path === "/replays") view = <Replays />;
  else if (path.startsWith("/replays/"))
    view = (
      <main className="page wrap">
        <header className="page-head">
          <p className="label">Replay</p>
          <h1 className="display-1">Every move matters</h1>
          <p className="page-lead">The completed game, one decision at a time.</p>
        </header>
        <div className="page-body">
          <Replay id={path.split("/")[2]} />
        </div>
      </main>
    );
  else if (path === "/auth") view = <Auth refresh={refresh} />;
  else if (path === "/verify") view = <VerifyPage />;
  else if (path === "/forgot") view = <ForgotPage />;
  else if (path === "/reset") view = <ResetPage />;
  else if (path === "/team") view = <Team me={me} refresh={refresh} />;
  else if (path === "/profile") view = <Profile me={me} refresh={refresh} />;
  else if (path === "/sponsors") view = <SponsorsPage />;
  else if (path === "/contact") view = <ContactPage />;
  else if (path === "/rules") view = <Rules />;
  else
    view = (
      <main className="page wrap">
        <header className="page-head">
          <p className="label">Not found</p>
          <h1 className="display-1">This table doesn't exist</h1>
        </header>
        <div className="page-body">
          <A to="/" className="text-button">
            Return home →
          </A>
        </div>
      </main>
    );

  const isPublic = ["/", "/arena", "/sponsors", "/contact"].includes(path);
  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="site-header">
        <div className="nav-wrap">
          <Brand />
          <nav className="site-nav" aria-label="Main">
            <A to="/" className={!isPublic || path === "/" ? "active" : ""}>
              Arena
            </A>
            <A to="/sponsors" className={path === "/sponsors" ? "active" : ""}>
              Sponsors
            </A>
            <A to="/contact" className={path === "/contact" ? "active" : ""}>
              Contact
            </A>
          </nav>
        </div>
      </header>
      {!isPublic && (
        <nav className="tools-strip" aria-label="Arena tools">
          <div className="inner wrap">
            {TOOLS.map(([href, label]) => (
              <A key={href} to={href} className={path.startsWith(href) ? "active" : ""}>
                {label}
              </A>
            ))}
            <A to={me?.user ? "/profile" : "/auth"} className="account">
              {me?.user ? me.user.name : "Sign in / Join"}
            </A>
          </div>
        </nav>
      )}
      <div id="main-content" tabIndex={-1}>
        <VerifyBanner me={me} />
        {view}
      </div>
      <footer className="footer">
        <div className="wrap footer-inner">
          <Brand />
          <p className="tagline">Where code comes to compete.</p>
          <nav aria-label="Footer">
            <A to="/">Arena</A>
            <A to="/sponsors">Sponsors</A>
            <A to="/contact">Contact</A>
          </nav>
          <small>Students submit Python agents. Bots play simulated poker for points, never money.</small>
        </div>
      </footer>
    </>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
