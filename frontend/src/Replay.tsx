import { useEffect, useState } from "react";
import { useData, type Data } from "./api";
import { Notice } from "./ui";

function CardFace({ card }: { card: string }) {
  const red = /[♥♦hd]$/i.test(card);
  return (
    <span className={"playing-card " + (red ? "red" : "")}>
      {card
        .replace(/h$/i, "♥")
        .replace(/d$/i, "♦")
        .replace(/s$/i, "♠")
        .replace(/c$/i, "♣")}
    </span>
  );
}

export function Replay({
  id,
  compact = false,
}: {
  id: string;
  compact?: boolean;
}) {
  const { data, error } = useData("/replays/" + id);
  const [index, setIndex] = useState(0);
  const frames = data?.frames || [];
  const [playing, setPlaying] = useState(false);
  useEffect(() => {
    setPlaying(false);
    const flop = compact
      ? (data?.frames ?? []).findIndex((frame: Data) => frame.board.length >= 3)
      : 0;
    setIndex(Math.max(0, flop));
  }, [id, data, compact]);
  useEffect(() => {
    if (!playing || !frames.length) return;
    const timer = window.setInterval(
      () =>
        setIndex((current) => {
          if (current >= frames.length - 1) return current;
          return current + 1;
        }),
      700,
    );
    return () => window.clearInterval(timer);
  }, [playing, frames.length]);
  useEffect(() => {
    if (index >= frames.length - 1) setPlaying(false);
  }, [index, frames.length]);
  const f = frames[Math.min(index, frames.length - 1)];
  return (
    <div className={"replay " + (compact ? "compact" : "")}>
      <div className="replay-bar">
        <span>
          <span style={{ color: "var(--red)" }}>●</span>{" "}
          {data?.title || "Exhibition replay"}
        </span>
        <span>{f ? `Hand ${f.hand} / ${f.street}` : "Loading table"}</span>
      </div>
      <Notice error={error} />
      {f && (
        <>
          <div className="table">
            <div className="seats">
              {f.seats.map((s: Data, i: number) => (
                <div
                  className={
                    "seat " +
                    (f.actor === i ? "acting" : "") +
                    (s.folded ? " folded" : "")
                  }
                  key={i}
                >
                  <b>{s.name}</b>
                  <small>
                    {s.stack} chips {s.folded ? "· folded" : ""}
                  </small>
                  <div className="hole">
                    {s.cards?.map((c: string, j: number) => (
                      <CardFace card={c} key={j} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
            <div className="board">
              <div className="board-cards">
                {f.board.map((c: string, i: number) => (
                  <CardFace card={c} key={i} />
                ))}
              </div>
              <span className="pot">Pot {f.pot}</span>
            </div>
          </div>
          <div className="replay-bottom">
            <span className="action-text">{f.action || f.note || "Hand in progress"}</span>
            <div className="replay-controls">
              <button
                aria-label="Previous frame"
                disabled={!index}
                onClick={() => setIndex(index - 1)}
              >
                ←
              </button>
              <button
                onClick={() => {
                  if (index >= frames.length - 1) setIndex(0);
                  setPlaying(!playing);
                }}
              >
                {playing ? "Pause" : "Play"}
              </button>
              <span>
                {index + 1} / {frames.length}
              </span>
              <button
                aria-label="Next frame"
                disabled={index >= frames.length - 1}
                onClick={() => setIndex(index + 1)}
              >
                →
              </button>
            </div>
          </div>
          {!compact && (
            <label className="replay-hand">
              Jump to hand{" "}
              <select
                value={f.hand}
                onChange={(e) => {
                  setPlaying(false);
                  setIndex(
                    frames.findIndex(
                      (frame: Data) => frame.hand === Number(e.target.value),
                    ),
                  );
                }}
              >
                {Array.from(new Set<number>(frames.map((frame: Data) => frame.hand))).map(
                  (hand) => (
                    <option key={hand} value={hand}>
                      {hand}
                    </option>
                  ),
                )}
              </select>
            </label>
          )}
          {!compact && (
            <input
              aria-label="Replay position"
              type="range"
              min="0"
              max={frames.length - 1}
              value={index}
              onChange={(e) => setIndex(+e.target.value)}
            />
          )}
          {!compact && (
            <details className="replay-history">
              <summary>Actions in this hand</summary>
              <ol>
                {frames
                  .slice(0, index + 1)
                  .filter(
                    (frame: Data) => frame.hand === f.hand && frame.action,
                  )
                  .map((frame: Data, i: number) => (
                    <li key={i}>
                      {frame.street}:{" "}
                      {frame.actor !== null && frame.seats[frame.actor]
                        ? `${frame.seats[frame.actor].name} — `
                        : ""}
                      {frame.action}
                    </li>
                  ))}
              </ol>
            </details>
          )}
        </>
      )}
    </div>
  );
}
