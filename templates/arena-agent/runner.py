#!/usr/bin/env python3
"""Baseline runner — prove your agent runs BEFORE you submit it to the arena.

Usage:
    python3 runner.py                 # validate agent.py against your game
    python3 runner.py --game uno      # override the game (default: GAME.txt)

What it checks (per recorded arena observation):
  1. act(observation) returns a dict with the right action vocabulary
  2. the agent is stable: calling it twice on the same observation works
  3. the agent is fast: the arena's real budget is per-event (1 ms classic /
     50 ms model-track), so anything slower than 50 ms per decision will
     time out in the sandbox
Exit code 0 = safe to push and connect to the arena. Non-zero = fix first.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent

VOCAB = {
    "poker": lambda r: isinstance(r, dict) and r.get("action") in ("fold", "check", "call", "raise"),
    "bluff": lambda r: isinstance(r, dict) and r.get("type") in ("play", "challenge", "pass"),
    "uno": lambda r: isinstance(r, dict) and r.get("type") in ("play", "draw", "pass", "uno", "challenge"),
    "hearts": lambda r: isinstance(r, dict) and r.get("type") in ("play", "pass"),
    "rummy": lambda r: isinstance(r, dict) and r.get("type") in ("draw", "discard", "declare", "pass"),
    "hexchange": lambda r: isinstance(r, dict) and r.get("type") in (
        "build_road", "build_settlement", "build_city", "buy_dev", "play_dev",
        "bank_trade", "offer", "accept", "reject", "counter", "move_robber",
        "setup_settlement", "setup_road", "end_turn", "pass"),
}


def load_agent(root: pathlib.Path):
    spec = importlib.util.spec_from_file_location("arena_agent", root / "agent.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    agent = module.Agent()
    if not callable(getattr(agent, "act", None)):
        raise SystemExit("agent.py must define class Agent with an act(self, observation) method.")
    if hasattr(agent, "reset"):
        agent.reset()
    return agent


def observations(game: str):
    path = ROOT / "games" / game / "observations.jsonl"
    if not path.exists():
        raise SystemExit(f"No fixtures for game '{game}'. Pick one of: {', '.join(VOCAB)}")
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def run(game: str) -> int:
    agent = load_agent(ROOT)
    vocab = VOCAB[game]
    obs_list = observations(game)
    failures, latencies = [], []
    print(f"agent vs {len(obs_list)} recorded {game} observations")
    for i, obs in enumerate(obs_list):
        t0 = time.perf_counter()
        try:
            reply = agent.act(obs)
        except Exception as exc:
            failures.append(f"observation {i}: act() raised {type(exc).__name__}: {exc}")
            continue
        latencies.append((time.perf_counter() - t0) * 1000)
        if not vocab(reply):
            failures.append(f"observation {i}: reply outside the {game} vocabulary: {reply!r}")
        try:
            again = agent.act(obs)
        except Exception as exc:
            failures.append(f"observation {i}: second call raised {type(exc).__name__}")
            continue
        if again != reply:
            print(f"  note: observation {i} got a different reply on re-run "
                  "(fine for stochastic agents, fatal for deterministic ones)")
    slow = [l for l in latencies if l > 50]
    if slow:
        failures.append(f"{len(slow)} decision(s) took > 50 ms — the sandbox will time these out")
    avg = sum(latencies) / len(latencies) if latencies else 0
    print(f"decisions: {len(latencies)} · avg {avg:.2f} ms · max {max(latencies, default=0):.2f} ms")
    if failures:
        print(f"\nFAIL — {len(failures)} problem(s):")
        for f in failures:
            print("  ✗", f)
        return 1
    print("\nPASS — safe to push and connect to the arena.")
    return 0


if __name__ == "__main__":
    game = sys.argv[sys.argv.index("--game") + 1] if "--game" in sys.argv else \
        (ROOT / "GAME.txt").read_text().strip() if (ROOT / "GAME.txt").exists() else "poker"
    sys.exit(run(game))
