import React from "react";

export function go(path: string) {
  history.pushState({}, "", path);
  dispatchEvent(new PopStateEvent("popstate"));
  window.scrollTo(0, 0);
}

export function A({
  to,
  children,
  className = "",
}: {
  to: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <a
      href={to}
      className={className}
      onClick={(e) => {
        if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        go(to);
      }}
    >
      {children}
    </a>
  );
}

export function Button({
  children,
  onClick,
  kind = "ink",
  disabled = false,
  type = "button",
}: {
  children: React.ReactNode;
  onClick?: () => void;
  kind?: string;
  disabled?: boolean;
  type?: "button" | "submit";
}) {
  return (
    <button className={"button " + kind} onClick={onClick} disabled={disabled} type={type}>
      {children}
    </button>
  );
}

export function Notice({ error }: { error: string | null | undefined }) {
  return error ? (
    <div className="notice" role="alert">
      {error}
    </div>
  ) : null;
}

const DATE = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" });
const DATE_LONG = new Intl.DateTimeFormat("en-US", {
  weekday: "short",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

export function fmtDay(value: string) {
  const d = new Date(value);
  return isNaN(d.getTime()) ? "" : DATE.format(d);
}

export function fmtLong(value: string) {
  const d = new Date(value);
  return isNaN(d.getTime()) ? "" : DATE_LONG.format(d);
}

export function Status({ text, done }: { text: string; done?: boolean }) {
  return <span className={"status-line" + (done ? " done" : "")}>{text}</span>;
}

export function Page({
  title,
  lead,
  eyebrow,
  children,
}: {
  title: string;
  lead?: string;
  eyebrow: string;
  children: React.ReactNode;
}) {
  return (
    <main className="page wrap">
      <header className="page-head">
        <p className="label">{eyebrow}</p>
        <h1 className="display-1">{title}</h1>
        {lead && <p className="page-lead">{lead}</p>}
      </header>
      <div className="page-body">{children}</div>
    </main>
  );
}
