import { useEffect, useRef, useState } from "react";

/**
 * Live Monte Carlo equity terminal. Two random Hold'em hands, one random
 * board, streets opening one at a time; win/tie/lose sampled in the browser
 * with a real 7-card evaluator, plus an "opening tree": every sampled path
 * from preflop, bucketed by who is stronger on the flop and the turn, with
 * river equity per leaf. No canned numbers anywhere.
 */

const RANKS = "23456789TJQKA";
const SUITS = ["♠", "♥", "♦", "♣"];
const ITERS = 6000;
const BAR_W = 22;
const BLOCKS = "▁▂▃▄▅▆▇█";

const cardStr = (c: number) => RANKS[c >> 2] + SUITS[c & 3];
const isRed = (c: number) => (c & 3) === 1 || (c & 3) === 2;

function combosOf(n: number, k: number): number[][] {
  const out: number[][] = [];
  const idx: number[] = [];
  (function walk(start: number) {
    if (idx.length === k) { out.push(idx.slice()); return; }
    for (let i = start; i < n; i++) { idx.push(i); walk(i + 1); idx.pop(); }
  })(0);
  return out;
}
const COMBOS: Record<number, number[][]> = { 5: combosOf(5, 5), 6: combosOf(6, 5), 7: combosOf(7, 5) };

const cnt = new Int16Array(15);

function score5(ranks: number[], flush: boolean): number {
  for (let i = 0; i < 5; i++) cnt[ranks[i]]++;
  const g: [number, number][] = [];
  for (let r = 14; r >= 2; r--) if (cnt[r]) g.push([r, cnt[r]]);
  for (let i = 0; i < 5; i++) cnt[ranks[i]] = 0;
  g.sort((a, b) => b[1] - a[1] || b[0] - a[0]);
  let straight = 0;
  if (g.length === 5) {
    if (g[0][0] - g[4][0] === 4) straight = g[0][0];
    else if (g[0][0] === 14 && g[1][0] === 5 && g[4][0] === 2) straight = 5;
  }
  const enc = (cat: number, k: number[]) => {
    let v = cat;
    for (let i = 0; i < 5; i++) v = v * 15 + (k[i] || 0);
    return v;
  };
  const a0 = g[0][0], c0 = g[0][1], a1 = g[1][0], c1 = g[1][1];
  if (flush && straight) return enc(8, [straight]);
  if (c0 === 4) return enc(7, [a0, a1]);
  if (c0 === 3 && c1 === 2) return enc(6, [a0, a1]);
  if (flush) return enc(5, g.map((x) => x[0]));
  if (straight) return enc(4, [straight]);
  if (c0 === 3) return enc(3, [a0, a1, g[2][0]]);
  if (c0 === 2 && c1 === 2) return enc(2, [a0, a1, g[2][0]]);
  if (c0 === 2) return enc(1, [a0, a1, g[2][0], g[3][0]]);
  return enc(0, g.map((x) => x[0]));
}

function bestOf(cards: number[]): number {
  const combos = COMBOS[cards.length];
  let best = -1;
  for (let k = 0; k < combos.length; k++) {
    const idx = combos[k];
    const s0 = cards[idx[0]] & 3;
    const flush =
      (cards[idx[1]] & 3) === s0 &&
      (cards[idx[2]] & 3) === s0 &&
      (cards[idx[3]] & 3) === s0 &&
      (cards[idx[4]] & 3) === s0;
    const v = score5(
      idx.map((i) => (cards[i] >> 2) + 2), // rank values 2..14
      flush,
    );
    if (v > best) best = v;
  }
  return best;
}

const cmp = (a: number, b: number) => (a > b ? 1 : a < b ? -1 : 0);

type Leaf = { runs: number; wins: number; ties: number };
type Branch = { runs: number; ahead: Leaf; behind: Leaf };
type TreeTally = { total: number; a: Branch; e: Branch; b: Branch };
type SimResult = {
  win: number; tie: number; lose: number; ms: number; iters: number;
  tree: TreeTally | null;
};

function newLeaf(): Leaf { return { runs: 0, wins: 0, ties: 0 }; }
function newBranch(): Branch { return { runs: 0, ahead: newLeaf(), behind: newLeaf() }; }

function simulate(hero: number[], villain: number[], board: number[], iters: number, withTree: boolean): SimResult {
  const known = new Set([...hero, ...villain, ...board]);
  const deck: number[] = [];
  for (let c = 0; c < 52; c++) if (!known.has(c)) deck.push(c);
  const need = 5 - board.length;
  const draw = Math.max(need, withTree ? 5 : need);
  const run = deck.slice();
  const sevenH = new Array(7);
  const sevenV = new Array(7);
  let win = 0, tie = 0, lose = 0;
  const tree: TreeTally | null = withTree
    ? { total: 0, a: newBranch(), e: newBranch(), b: newBranch() }
    : null;
  const t0 = performance.now();
  for (let i = 0; i < iters; i++) {
    for (let j = 0; j < draw; j++) {
      const k = j + ((Math.random() * (run.length - j)) | 0);
      const t = run[j]; run[j] = run[k]; run[k] = t;
    }
    for (let j = 0; j < board.length; j++) { sevenH[j] = board[j]; sevenV[j] = board[j]; }
    for (let j = 0; j < need; j++) { sevenH[board.length + j] = run[j]; sevenV[board.length + j] = run[j]; }
    sevenH[5] = hero[0]; sevenH[6] = hero[1];
    sevenV[5] = villain[0]; sevenV[6] = villain[1];
    const hv = bestOf(sevenH), vv = bestOf(sevenV);
    const out = cmp(hv, vv);
    if (out > 0) win++; else if (out < 0) lose++; else tie++;
    if (tree) {
      // Opening tree: fresh runout from preflop (run cards 0..4 regardless
      // of the visible board), bucketed by strength on flop and turn.
      const flopH = [hero[0], hero[1], run[0], run[1], run[2]];
      const flopV = [villain[0], villain[1], run[0], run[1], run[2]];
      const turnH = flopH.concat([run[3]]);
      const turnV = flopV.concat([run[3]]);
      const fc = cmp(bestOf(flopH), bestOf(flopV));
      const tc = cmp(bestOf(turnH), bestOf(turnV));
      const branch = fc > 0 ? tree.a : fc === 0 ? tree.e : tree.b;
      const leaf = tc > 0 ? branch.ahead : branch.behind;
      branch.runs++; leaf.runs++;
      if (out > 0) leaf.wins++; else if (out === 0) leaf.ties++;
      tree.total++;
    }
  }
  return {
    win: win / iters, tie: tie / iters, lose: lose / iters,
    ms: Math.round(performance.now() - t0), iters, tree,
  };
}

function pickMatchup() {
  const deck = Array.from({ length: 52 }, (_, i) => i);
  for (let i = deck.length - 1; i > 0; i--) {
    const j = (Math.random() * (i + 1)) | 0;
    [deck[i], deck[j]] = [deck[j], deck[i]];
  }
  return {
    hero: [deck[0], deck[1]] as number[],
    villain: [deck[2], deck[3]] as number[],
    fullBoard: [deck[4], deck[5], deck[6], deck[7], deck[8]] as number[],
  };
}

const STREETS = ["preflop", "flop", "turn", "river"];
const BOARD_LEN = [0, 3, 4, 5];
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function Card({ card }: { card: number | null }) {
  if (card === null) return <span className="eq-card empty">··</span>;
  return <span className={"eq-card" + (isRed(card) ? " red" : "")}>{cardStr(card)}</span>;
}

function Hand({ cards, who }: { cards: number[]; who: string }) {
  return (
    <span className="eq-hand">
      <span className="eq-who">{who}</span>{" "}
      <span className="eq-cards">
        {cards.map((c, i) => (
          <span key={i} className={isRed(c) ? "red" : ""}>{cardStr(c)}</span>
        ))}
      </span>
    </span>
  );
}

function asciiBar(pct: number) {
  const fill = Math.round((pct / 100) * BAR_W);
  return { fill, rest: BAR_W - fill };
}

type TreeRowSeg = { text: string; cls?: string };

const LEAF_CW = 11;

function buildTreeGrid(tree: TreeTally | null, trunk: number | null, street: number): Array<TreeRowSeg[]> {
  if (trunk === null || !tree) {
    const sampling: Array<TreeRowSeg[]> = [[{ text: "└── sampling the paths…" }]];
    return sampling;
  }
  const pct = (x: number) => (x * 100).toFixed(1);
  const leafX = (li: number) => li * LEAF_CW + LEAF_CW / 2;
  const branchX = [0, 1, 2].map((b) => (leafX(b * 2) + leafX(b * 2 + 1)) / 2);
  const rootX = branchX[1];
  const W = 6 * LEAF_CW;
  const rows: Array<TreeRowSeg[]> = [];

  const labelRow = (x: number, text: string, cls?: string): TreeRowSeg[] => {
    const start = Math.max(0, Math.round(x - text.length / 2));
    return [{ text: " ".repeat(start) + text, cls }];
  };
  function marksRow(marks: Record<number, string>, fill?: [number, number]): TreeRowSeg[] {
    const arr = new Array(W).fill(" ");
    if (fill) {
      const [a, b] = fill;
      for (let c = a; c <= b; c++) arr[c] = "─";
    }
    for (const [col, ch] of Object.entries(marks)) {
      const c = Math.max(0, Math.min(W - 1, +col));
      arr[c] = ch;
    }
    return [{ text: arr.join("").replace(/\s+$/, "") }];
  }

  // r0 · trunk
  rows.push(labelRow(rootX, `preflop equity ${pct(trunk)}%`, "trunk"));
  rows.push(marksRow({ [rootX]: "│" }));
  if (street < 1) return rows;

  // r2 · first split into flop states
  rows.push(marksRow(
    { [branchX[0]]: "┌", [branchX[1]]: "┼", [branchX[2]]: "┐", [rootX]: "┴" },
    [branchX[0], branchX[2]],
  ));
  const branches: [Branch, string][] = [[tree.a, "ahead"], [tree.e, "even"], [tree.b, "behind"]];
  branches.forEach(([branch, label], i) => {
    rows.push(labelRow(branchX[i], `${label} ${(branch.runs / tree.total * 100).toFixed(1)}%`));
  });
  if (street < 2) return rows;

  // verticals + second split per branch
  rows.push(marksRow({ [branchX[0]]: "│", [branchX[1]]: "│", [branchX[2]]: "│" }));
  const splitRow: Record<number, string> = {};
  branches.forEach((_, i) => {
    const c1 = leafX(i * 2), c2 = leafX(i * 2 + 1);
    splitRow[c1] = "┌";
    splitRow[(c1 + c2) / 2] = "┴";
    splitRow[c2] = "┐";
    for (let c = c1 + 1; c < c2; c++) if (!(c in splitRow)) splitRow[c] = "─";
  });
  rows.push(marksRow(splitRow));

  // leaf labels: ▲ = still ahead at turn, ▼ = fell behind
  const leafRow: TreeRowSeg[] = [];
  branches.forEach(([branch], i) => {
    [branch.ahead, branch.behind].forEach((leaf, j) => {
      const x = leafX(i * 2 + j);
      const share = (leaf.runs / tree.total * 100).toFixed(1);
      leafRow.push({ text: " ".repeat(Math.max(0, Math.round(x - 4))) + (j === 0 ? "▲" : "▼") + " " + share + "%" });
    });
  });
  rows.push(leafRow);
  if (street < 3) return rows;

  rows.push(marksRow(
    Object.fromEntries(
      [0, 1, 2].flatMap((b) => [leafX(b * 2), leafX(b * 2 + 1)]).map((x) => [x, "│"]),
    ),
  ));

  // terminal river equity per leaf
  const termRow: TreeRowSeg[] = [];
  branches.forEach(([branch], i) => {
    [branch.ahead, branch.behind].forEach((leaf, j) => {
      const x = leafX(i * 2 + j);
      const eq = leaf.runs ? (leaf.wins + leaf.ties / 2) / leaf.runs : null;
      const text = eq === null ? "—" : "→ " + pct(eq) + "%";
      termRow.push({ text: " ".repeat(Math.max(0, Math.round(x - 3.5))) + text, cls: eq !== null && eq >= 0.5 ? "good" : undefined });
    });
  });
  rows.push(termRow);
  return rows;
}

export function EquityPanel() {
  const [matchup, setMatchup] = useState(() => pickMatchup());
  const [board, setBoard] = useState<number[]>([]);
  const [street, setStreet] = useState(0);
  const [result, setResult] = useState<SimResult | null>(null);
  const [display, setDisplay] = useState({ win: 0, tie: 0, lose: 0 });
  const [hist, setHist] = useState<number[]>([]);
  const [tree, setTree] = useState<TreeTally | null>(null);
  const [trunk, setTrunk] = useState<number | null>(null);
  const [trial, setTrial] = useState(1);
  const [total, setTotal] = useState(0);
  const displayRef = useRef(display);

  useEffect(() => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let alive = true;
    async function run() {
      for (let cycle = 0; ; cycle++) {
        if (!alive) return;
        const m = pickMatchup();
        setMatchup(m); setBoard([]); setStreet(0); setHist([]);
        setResult(null); setTree(null); setTrunk(null); setTrial((t) => t + 1);
        for (let s = 0; s < 4; s++) {
          if (!alive) return;
          const shown = m.fullBoard.slice(0, BOARD_LEN[s]);
          setBoard(shown); setStreet(s);
          await sleep(reduce ? 0 : 60);
          const res = simulate(m.hero, m.villain, shown, ITERS, s === 0);
          if (!alive) return;
          setResult(res);
          if (res.tree) { setTree(res.tree); setTrunk(res.win + res.tie / 2); }
          setHist((h) => [...h, res.win]);
          setTotal((n) => n + res.iters);
          await sleep(reduce ? 0 : 1150);
        }
        if (reduce) return;
        await sleep(1900);
        if (!alive) return;
      }
    }
    run();
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!result) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      displayRef.current = { win: result.win, tie: result.tie, lose: result.lose };
      setDisplay({ win: result.win, tie: result.tie, lose: result.lose });
      return;
    }
    const from = { ...displayRef.current };
    const start = performance.now();
    let raf = 0;
    const tick = () => {
      const t = Math.min(1, (performance.now() - start) / 550);
      const e = 1 - Math.pow(1 - t, 4);
      const next = {
        win: from.win + (result.win - from.win) * e,
        tie: from.tie + (result.tie - from.tie) * e,
        lose: from.lose + (result.lose - from.lose) * e,
      };
      displayRef.current = next;
      setDisplay(next);
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [result]);

  const winPct = display.win * 100, tiePct = display.tie * 100, losePct = display.lose * 100;
  const spark = hist.map((h) => BLOCKS[Math.min(7, Math.floor(h * 8))]).join("");

  return (
    <div className="equity" aria-label="Live Monte Carlo poker equity simulation with an opening-probability tree, computed in this browser">
      <div className="equity-head">
        <span>live equity · monte carlo</span>
        <span>trial #{String(trial).padStart(4, "0")}</span>
      </div>
      <div className="eq-matchup">
        <Hand cards={matchup.hero} who="hero" />
        <span className="eq-vs">vs</span>
        <Hand cards={matchup.villain} who="villain" />
      </div>
      <div className="eq-board" aria-label="Community cards">
        {[0, 1, 2, 3, 4].map((i) => (
          <Card key={i} card={board[i] ?? null} />
        ))}
      </div>
      <div className="eq-streets" aria-hidden="true">
        {STREETS.map((s, i) => (
          <span key={s} className={i === street ? "now" : i < street ? "done" : ""}>
            {s}
          </span>
        ))}
      </div>
      <div className="eq-rows">
        <div className="eq-row win">
          <span className="lab">win</span>
          <span className="art">
            <i>{"█".repeat(asciiBar(winPct).fill)}</i>
            {"░".repeat(asciiBar(winPct).rest)}
          </span>
          <b>{winPct.toFixed(1)}%</b>
        </div>
        <div className="eq-row">
          <span className="lab">tie</span>
          <span className="art">
            <i>{"█".repeat(asciiBar(tiePct).fill)}</i>
            {"░".repeat(asciiBar(tiePct).rest)}
          </span>
          <b>{tiePct.toFixed(1)}%</b>
        </div>
        <div className="eq-row">
          <span className="lab">lose</span>
          <span className="art">
            <i>{"█".repeat(asciiBar(losePct).fill)}</i>
            {"░".repeat(asciiBar(losePct).rest)}
          </span>
          <b>{losePct.toFixed(1)}%</b>
        </div>
      </div>
      <div className="eq-tree">
        <div className="eq-tree-label">
          opening tree · ▲ still ahead at turn ▼ behind · {tree ? tree.total.toLocaleString("en-US") : "…"} paths from preflop
        </div>
        {buildTreeGrid(tree, trunk, street).map((segments, i) => (
          <div key={i} className="eq-tree-line">
            {segments.map((s, j) => (
              <span key={j} className={s.cls}>{s.text}</span>
            ))}
          </div>
        ))}
      </div>
      <div className="eq-spark">
        hero equity by street <span className="blocks">{spark || "···"}</span>
      </div>
      <div className="equity-foot">
        <span>{total.toLocaleString("en-US")} hands sampled in this browser</span>
        <span>{result ? `${result.iters.toLocaleString("en-US")} draws · ${result.ms} ms` : "sampling…"}</span>
      </div>
    </div>
  );
}
