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

function BluffReplay({ data, compact = false }: { data: Data; compact?: boolean }) {
  const wrapper = data.frames || {};
  const names: string[] = wrapper.names || [];
  const frames: Data[] = wrapper.frames || [];
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  useEffect(() => setIndex(0), [data]);
  useEffect(() => {
    if (!playing || !frames.length) return;
    const timer = window.setInterval(
      () => setIndex((current) => (current >= frames.length - 1 ? current : current + 1)),
      700,
    );
    return () => window.clearInterval(timer);
  }, [playing, frames.length]);
  useEffect(() => {
    if (index >= frames.length - 1) setPlaying(false);
  }, [index, frames.length]);
  const f = frames[Math.min(index, frames.length - 1)];
  const rankLabel = (rank: string) => (rank === "T" ? "10" : rank);
  const summary = data.summary || {};
  return (
    <div className={"replay " + (compact ? "compact" : "")}>
      <div className="replay-bar">
        <span>
          <span style={{ color: "var(--red)" }}>●</span> {data.title || "Bluff replay"}
        </span>
        <span>{f ? `Decision ${index + 1} / ${frames.length}` : "Loading match"}</span>
      </div>
      {f && (
        <>
          <div className="table bluff-table">
            <div className="seats">
              {(f.counts || []).map((count: number, seat: number) => {
                const acted = ["play", "challenge", "pass"].includes(f.kind) && f.seat === seat;
                const took = f.kind === "resolution" && f.taken_by === seat;
                const won = f.kind === "end" && (f.winner_seats || []).includes(seat);
                return (
                  <div
                    className={"seat bluff-seat " + (acted || took || won ? "acting" : "")}
                    key={seat}
                  >
                    <b>{names[seat] || `Seat ${seat + 1}`}</b>
                    <small>
                      {won ? "★ winner · " : ""}
                      {count} card{count === 1 ? "" : "s"}
                      {took ? " · picks up pile" : ""}
                    </small>
                  </div>
                );
              })}
            </div>
            <div className="bluff-state">
              {f.kind === "play" && (
                <span className="action-text">
                  Seat {f.seat} claims {f.count} × {rankLabel(f.rank)}
                </span>
              )}
              {f.kind === "challenge" && (
                <span className="action-text">Seat {f.seat} says: I doubt it!</span>
              )}
              {f.kind === "pass" && (
                <span className="action-text">Seat {f.seat} passes</span>
              )}
              {f.kind === "resolution" && (
                <span className="action-text">
                  {f.challenged_by !== null && f.challenged_by !== undefined
                    ? `Challenged by seat ${f.challenged_by} — ${
                        f.honest ? "the claim was honest" : "caught lying"
                      }${f.taken_by !== null && f.taken_by !== undefined ? `, seat ${f.taken_by} takes the pile` : ""}`
                    : "Everyone passed — the batch stays face down"}
                </span>
              )}
              {f.kind === "end" && (
                <span className="action-text">
                  {f.reason === "cap" ? "Decision cap reached — fewest cards wins" : "Match over"}
                </span>
              )}
              <span className="pot">
                Pile {f.pile_size ?? (f.kind === "play" ? f.count : 0)} · next rank{" "}
                {rankLabel(f.next_rank || "A")}
              </span>
            </div>
            {f.revealed && f.revealed.length > 0 && (
              <div className="board">
                <div className="board-cards" aria-label="Revealed challenged batch">
                  {f.revealed.map((card: string, i: number) => (
                    <CardFace card={card} key={i} />
                  ))}
                </div>
                <span className="pot">Revealed batch</span>
              </div>
            )}
          </div>
          <div className="replay-bottom">
            <span className="action-text">
              {summary.terminal_reason
                ? `Result: ${summary.terminal_reason}`
                : "Bluff · Stack Theory v1"}
            </span>
            <div className="replay-controls">
              <button aria-label="Previous frame" disabled={!index} onClick={() => setIndex(index - 1)}>
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
            <input
              aria-label="Replay position"
              type="range"
              min="0"
              max={Math.max(0, frames.length - 1)}
              value={index}
              onChange={(e) => setIndex(+e.target.value)}
            />
          )}
          {!compact && (
            <details className="replay-history">
              <summary>Decisions so far</summary>
              <ol>
                {frames.slice(0, index + 1).map((frame: Data, i: number) => (
                  <li key={i}>
                    {frame.kind === "play" &&
                      `Seat ${frame.seat} claims ${frame.count} × ${rankLabel(frame.rank)}`}
                    {frame.kind === "challenge" && `Seat ${frame.seat} challenges`}
                    {frame.kind === "pass" && `Seat ${frame.seat} passes`}
                    {frame.kind === "resolution" &&
                      (frame.challenged_by !== null && frame.challenged_by !== undefined
                        ? `Resolved: challenged by ${frame.challenged_by}, seat ${frame.taken_by} takes the pile`
                        : "Resolved: all passed")}
                    {frame.kind === "end" && "Match ends"}
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

/** Generic replay renderer for the four post-poker engines (uno, hearts,
 *  rummy, hexchange). Frames are {kind, counts, seat?, ...} — rendered with
 *  per-game copy templates and a defensive fallback, never leaking state. */
const UNIT_LABEL: Record<string, string> = {
  uno: "cards", hearts: "cards", rummy: "cards", hexchange: "tokens",
};

function seatName(names: string[], seat: number | null | undefined) {
  if (seat === null || seat === undefined || !names.length) return "";
  return names[seat] || `Seat ${seat + 1}`;
}

function describeFrame(game: string, f: Data, names: string[]): string {
  const s = (n: number | null | undefined) => seatName(names, n);
  const who = s(f.seat);
  const kind: string = f.kind || "";
  if (game === "uno") {
    const map: Record<string, string> = {
      start: "Cards dealt",
      play: `${who} plays ${f.card ?? ""}`,
      draw: `${who} draws`,
      pass: `${who} passes`,
      uno: `${who} calls UNO!`,
      uno_penalty: `${who} caught — UNO penalty`,
      penalty: `${who} serves the draw penalty`,
      skip: `${who} is skipped`,
      reverse: "Direction reverses",
      challenge: `${who} challenges the wild draw-four`,
      challenge_result: "Challenge resolved",
      reshuffle: "Deck exhausted — discards reshuffled",
    };
    return map[kind] ?? kind;
  }
  if (game === "hearts") {
    const map: Record<string, string> = {
      pass: `${who} passes 3 cards`,
      play: `${who} plays ${f.card ?? "a card"}`,
      trick: `${s(f.winner)} takes the trick${f.points ? ` (+${f.points})` : ""}`,
      end: "Hand complete — fewest points wins",
    };
    return map[kind] ?? kind;
  }
  if (game === "rummy") {
    const map: Record<string, string> = {
      draw: `${who} draws from ${f.from ?? "the stock"}`,
      discard: `${who} discards ${f.card ?? ""}`,
      declaration: `${who} declares!`,
      wrong_declaration: `${who} shows a wrong declaration — penalty`,
      reshuffle: "Stock exhausted — discards reshuffled",
      end: "Match over",
    };
    return map[kind] ?? kind;
  }
  if (game === "hexchange") {
    const map: Record<string, string> = {
      roll: `Dice: ${f.roll ?? "?"}`,
      production: "Production",
      build: `${who} builds ${f.built ?? ""}`,
      bank_trade: `${who} trades with the bank`,
      offer: `${who} offers ${f.give ? JSON.stringify(f.give) : ""} for ${f.want ? JSON.stringify(f.want) : ""}`,
      accept: `${who} accepts the offer`,
      reject: `${who} rejects`,
      counter: `${who} counters`,
      trade_expired: "Trade window closes",
      dev_bought: `${who} buys a development card`,
      dev_played: `${who} plays a development card`,
      robber: `Robber moves${f.stole_from ? ` — steals from ${s(f.stole_from)}` : ""}`,
      discard: `${who} discards`,
      end_turn: `${who} ends the turn`,
      end: "Match over",
    };
    return map[kind] ?? kind;
  }
  return kind;
}

function GameReplay({ data, compact = false }: { data: Data; compact?: boolean }) {
  const wrapper = data.frames || {};
  const names: string[] = wrapper.names || [];
  const frames: Data[] = wrapper.frames || [];
  const unit = UNIT_LABEL[data.game] || "cards";
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  useEffect(() => setIndex(0), [data]);
  useEffect(() => {
    if (!playing || !frames.length) return;
    const timer = window.setInterval(
      () => setIndex((c) => (c >= frames.length - 1 ? c : c + 1)),
      700,
    );
    return () => window.clearInterval(timer);
  }, [playing, frames.length]);
  useEffect(() => {
    if (index >= frames.length - 1) setPlaying(false);
  }, [index, frames.length]);
  const f = frames[Math.min(index, frames.length - 1)];
  const cardsShown: string[] = f?.revealed ?? (f?.card ? [f.card] : f?.cards ?? []);
  return (
    <div className={"replay " + (compact ? "compact" : "")}>
      <div className="replay-bar">
        <span>
          <span style={{ color: "var(--red)" }}>●</span> {data.title || "Replay"}
        </span>
        <span>{f ? `Move ${index + 1} / ${frames.length}` : "Loading match"}</span>
      </div>
      {f && (
        <>
          <div className="table bluff-table">
            <div className="seats">
              {(f.counts || []).map((count: number, seat: number) => (
                <div
                  className={"seat bluff-seat" + (f.seat === seat ? " acting" : "")}
                  key={seat}
                >
                  <b>{names[seat] || `Seat ${seat + 1}`}</b>
                  <small>{count} {unit}{count === 1 ? "" : ""}</small>
                </div>
              ))}
            </div>
            <div className="bluff-state">
              <span className="action-text">{describeFrame(data.game, f, names)}</span>
            </div>
            {cardsShown.length > 0 && (
              <div className="board">
                <div className="board-cards">
                  {cardsShown.map((card: string, i: number) => (
                    <CardFace card={card} key={i} />
                  ))}
                </div>
              </div>
            )}
          </div>
          <div className="replay-bottom">
            <span className="action-text">{data.summary?.terminal_reason ? `Result: ${data.summary.terminal_reason}` : "Every decision, in order."}</span>
            <div className="replay-controls">
              <button aria-label="Previous frame" disabled={!index} onClick={() => setIndex(index - 1)}>←</button>
              <button onClick={() => { if (index >= frames.length - 1) setIndex(0); setPlaying(!playing); }}>
                {playing ? "Pause" : "Play"}
              </button>
              <span>{index + 1} / {frames.length}</span>
              <button aria-label="Next frame" disabled={index >= frames.length - 1} onClick={() => setIndex(index + 1)}>→</button>
            </div>
          </div>
          {!compact && (
            <input aria-label="Replay position" type="range" min="0" max={Math.max(0, frames.length - 1)}
              value={index} onChange={(e) => setIndex(+e.target.value)} />
          )}
        </>
      )}
    </div>
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
  if (error) {
    return (
      <div className={"replay " + (compact ? "compact" : "")}>
        <div className="replay-bar">
          <span>Replay</span>
        </div>
        <Notice error={error} />
      </div>
    );
  }
  if (!data) {
    return (
      <div className={"replay " + (compact ? "compact" : "")}>
        <div className="replay-bar">
          <span>Loading replay…</span>
        </div>
      </div>
    );
  }
  if (data.game === "bluff") return <BluffReplay data={data} compact={compact} />;
  if (["uno", "hearts", "rummy", "hexchange"].includes(data.game))
    return <GameReplay data={data} compact={compact} />;
  return <PokerReplay id={id} compact={compact} />;
}

function PokerReplay({
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
    setIndex(0);
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
