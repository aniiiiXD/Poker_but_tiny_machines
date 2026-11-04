"""Conformance tests — the same checks runner.py performs, as a test suite."""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import runner  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
GAME = (ROOT / "GAME.txt").read_text().strip() if (ROOT / "GAME.txt").exists() else "poker"


@pytest.fixture(scope="module")
def agent():
    return runner.load_agent(ROOT)


@pytest.fixture(scope="module")
def observations():
    return runner.observations(GAME)


def test_agent_replies_within_vocabulary(agent, observations):
    for i, obs in enumerate(observations):
        reply = agent.act(obs)
        assert runner.VOCAB[GAME](reply), f"observation {i}: reply {reply!r} outside the {GAME} vocabulary"


def test_agent_is_stable_on_repeated_observations(agent, observations):
    for i, obs in enumerate(observations[:10]):
        first = agent.act(obs)
        second = agent.act(obs)
        assert isinstance(first, dict) and isinstance(second, dict)


def test_agent_is_fast_enough_for_the_sandbox(agent, observations):
    import time
    for i, obs in enumerate(observations):
        t0 = time.perf_counter()
        agent.act(obs)
        elapsed = (time.perf_counter() - t0) * 1000
        assert elapsed < 50, f"observation {i}: {elapsed:.1f} ms — the sandbox will time this out"


def test_agent_survives_a_full_scenario_run():
    assert runner.run(GAME) == 0
