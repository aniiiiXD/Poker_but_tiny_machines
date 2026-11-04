# Arena agent template

Ship an agent that **runs the first time**. This repo gives you the interface,
recorded real observations from the arena engines, conformance tests, a
baseline runner, and CI — so by the time you push, submission is a formality.

## Pick your game

```sh
cp games/hearts/agent.py agent.py   # or bluff, uno, rummy, hexchange, poker
echo hearts > GAME.txt
python3 runner.py                   # must print PASS
pytest                              # same checks as tests
```

Then either submit `agent.py` in the arena Workshop, or push this repo (make
it public, or install the arena GitHub App on it) and connect the branch —
the arena fetches `agent.py`, smoke-tests it in an isolated sandbox, and
activates it on green.

## Structure

- `agent.py` — your agent (class `Agent`, method `act(observation) -> dict`)
- `GAME.txt` — which game this repo targets
- `games/<game>/agent.py` — that game's starter, with the protocol in its docstring
- `games/<game>/observations.jsonl` — **real observations recorded from the arena engines**
- `tests/test_agent.py` — vocabulary, stability, speed
- `runner.py` — the same checks as a CLI (CI-friendly exit codes)
- `.github/workflows/validate.yml` — runs the checks on every push

## The one rule

`act(observation)` must always return a legal action **fast** — the sandbox
enforces a per-event decision deadline (1 ms classic track, 50 ms model track)
and the arena never leaks hidden state: everything your agent sees is public
information plus its own hand. If your agent errors or times out, the engine
falls back to a legal move and records a fault — faults lose games.
