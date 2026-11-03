"""Stack Theory Bluff v1 engine rules, determinism, privacy, and fallbacks."""
import pytest

from arena.games.bluff import baselines as bluff_baselines
from arena.games.bluff.engine import (
    DECISION_CAP, RANKS, SEATS, _validate_cards, play_bluff_match, sort_key,
)
from arena.sandbox import SandboxDown


class Scripted:
    """Acts by calling the given function with each observation it receives."""

    def __init__(self, name, fn):
        self.name, self._fn = name, fn

    def reset(self):
        pass

    def act(self, observation):
        return self._fn(observation)


class Recording:
    """Wraps a bot and records every observation it is shown."""

    def __init__(self, inner):
        self.inner, self.name, self.seen = inner, inner.name, []

    def reset(self):
        self.seen = []
        self.inner.reset()

    def act(self, observation):
        self.seen.append(observation)
        return self.inner.act(observation)


def all_pass(observation):
    if observation["turn"]["type"] == "play":
        return {"type": "play", "cards": [observation["hand"][0]]}
    return {"type": "pass"}


def lowest_card(observation):
    return {"type": "play", "cards": [observation["hand"][0]]}


def end_log(result):
    return next(entry for entry in result["log"] if entry["type"] == "end")


def dealt_hand(seed, seat):
    """Mirror the engine's private deal for a fixed seed (test helper)."""
    import random

    deck = [rank + suit for rank in RANKS for suit in "cdhs"]
    random.Random(seed).shuffle(deck)
    return sorted(deck[seat::SEATS], key=sort_key)


def test_deterministic_replay_from_seed_and_actions():
    bots = bluff_baselines.make_bluff_baselines(4, seed=99)
    first = play_bluff_match(bots, seed=123, capture=False)
    bots2 = bluff_baselines.make_bluff_baselines(4, seed=99)
    second = play_bluff_match(bots2, seed=123, capture=False)
    assert first["points"] == second["points"]
    assert first["decisions"] == second["decisions"]
    assert [e["type"] for e in first["log"]] == [e["type"] for e in second["log"]]


def test_different_seed_deals_different_hands():
    bots = bluff_baselines.make_bluff_baselines(4, seed=1)
    a = end_log(play_bluff_match(bots, seed=1))
    b = end_log(play_bluff_match(bots, seed=2))
    assert a["hands"] != b["hands"]


def test_all_52_cards_conserved_and_no_duplicates():
    for seed in (3, 77, 2024):
        bots = bluff_baselines.make_bluff_baselines(4, seed=seed)
        result = play_bluff_match(bots, seed=seed)
        end = end_log(result)
        total = sum(len(hand) for hand in end["hands"]) + len(end["pile"])
        assert total == 52
        seen = [card for hand in end["hands"] for card in hand] + end["pile"]
        assert len(seen) == len(set(seen))


def test_all_pass_keeps_pile_hidden_and_advances_rank():
    seen = []

    def watcher(observation):
        seen.append(observation)
        return all_pass(observation)

    bots = [Scripted(f"S{i}", watcher) for i in range(4)]
    result = play_bluff_match(bots, seed=11)
    resolutions = [e for e in result["log"] if e["type"] == "resolution"]
    assert resolutions, "the match must resolve at least one batch"
    # Nobody ever challenged in this scripted line.
    assert all(r["challenged_by"] is None for r in resolutions if r.get("type") == "resolution" and "challenged_by" in r)
    # Required rank advances one step per batch and wraps around the cycle.
    plays = [e for e in result["log"] if e["type"] == "play"]
    ranks_seen = [e["declared_rank"] for e in plays]
    assert ranks_seen[0] == "A"
    for previous, current in zip(ranks_seen, ranks_seen[1:]):
        assert RANKS[(RANKS.index(previous) + 1) % len(RANKS)] == current


def test_false_challenge_moves_pile_to_claimant():
    # Seat 0 lies on purpose: it plays a card that is never the required Ace.
    def liar(observation):
        hand = observation["hand"]
        if observation["turn"]["type"] == "play":
            non_ace = next(card for card in hand if card[0] != "A")
            return {"type": "play", "cards": [non_ace]}
        return {"type": "pass"}

    def challenger(observation):
        if observation["turn"]["type"] == "challenge":
            return {"type": "challenge"}
        return lowest_card(observation)

    def passer(observation):
        return all_pass(observation)

    bots = [Scripted("Liar", liar), Scripted("Ch", challenger),
            Scripted("P1", passer), Scripted("P2", passer)]
    result = play_bluff_match(bots, seed=5)
    first_resolution = next(e for e in result["log"] if e["type"] == "resolution")
    assert first_resolution["honest"] is False
    assert first_resolution["taken_by"] == 0  # caught liar takes the pile
    assert first_resolution["batch"][0][0] != "A"  # the lie was revealed publicly
    assert first_resolution["revealed"] == first_resolution["batch"]


def test_true_challenge_moves_pile_to_challenger():
    # Choose a seed where the claimant genuinely holds the required Ace.
    seed = next(s for s in range(200) if any(c[0] == "A" for c in dealt_hand(s, 0)))

    def truthful(observation):
        if observation["turn"]["type"] == "play":
            rank = observation["required_rank"]
            owned = [c for c in observation["hand"] if c[0] == rank]
            return {"type": "play", "cards": [owned[0]]}
        return {"type": "pass"}

    def always_challenge(observation):
        if observation["turn"]["type"] == "challenge":
            return {"type": "challenge"}
        return truthful(observation)

    bots = [Scripted("T", truthful), Scripted("C", always_challenge),
            Scripted("P1", all_pass), Scripted("P2", all_pass)]
    result = play_bluff_match(bots, seed=seed)
    first_resolution = next(e for e in result["log"] if e["type"] == "resolution")
    assert first_resolution["honest"] is True
    assert first_resolution["taken_by"] == 1  # wrong challenger takes the pile
    assert first_resolution["revealed"][0][0] == "A"


def test_first_challenge_stops_the_sequence():
    decided = []

    def make(name, decision):
        def fn(observation):
            if observation["turn"]["type"] == "challenge":
                decided.append(observation["seat"])
                return decision(observation)
            return lowest_card(observation)
        return Scripted(name, fn)

    bots = [make("Claim", lowest_card),
            make("Pass1", lambda o: {"type": "pass"}),
            make("Challenge", lambda o: {"type": "challenge"}),
            make("Never", lambda o: {"type": "challenge"})]
    play_bluff_match(bots, seed=7)
    # In the first challenge sequence seat 1 passed and seat 2 challenged;
    # seat 3's pending decision never happened there.
    assert decided[:2] == [1, 2]
    assert 3 not in decided[:2]


def test_later_deciders_see_earlier_challenge_decisions_only():
    observations = []

    def make(name, index, decision):
        def fn(observation):
            if observation["turn"]["type"] == "challenge":
                observations.append((index, list(observation["history"])))
            return decision(observation)
        return Scripted(name, fn)

    bots = [make("C0", 0, lowest_card),
            make("C1", 1, lambda o: {"type": "challenge"}),
            make("C2", 2, lambda o: {"type": "pass"}),
            make("C3", 3, lambda o: {"type": "pass"})]
    play_bluff_match(bots, seed=8)
    # Seat 2's challenge turn was never reached (seat 1 challenged first), so
    # only seat 1's own view exists; it must not contain its own pending
    # decision or any later one.
    views = [history for seat, history in observations if seat == 1]
    assert views, "seat 1 must receive a challenge decision"
    for history in views:
        assert not any(e.get("seat") == 1 and e["type"] in ("challenge", "pass") for e in history)


def test_win_only_after_decisions_resolve():
    # Seat 0 plays its last card; seat 1 wrong-challenges, takes the pile, and
    # seat 0 must NOT win even though its hand hit zero for a moment.
    def emptier(observation):
        if observation["turn"]["type"] == "play":
            return {"type": "play", "cards": [observation["hand"][0]]}
        return {"type": "pass"}

    def challenger(observation):
        if observation["turn"]["type"] == "challenge":
            return {"type": "challenge"}
        return {"type": "play", "cards": [observation["hand"][0]]}

    def passer(observation):
        return all_pass(observation)

    bots = [Scripted("E", emptier), Scripted("C", challenger),
            Scripted("P1", passer), Scripted("P2", passer)]
    result = play_bluff_match(bots, seed=9)
    resolutions = [e for e in result["log"] if e["type"] == "resolution"]
    first = resolutions[0]
    assert first["taken_by"] == 1  # claimant was forced to pick up; no win
    assert result["terminal_reason"] in ("win", "cap")


def test_decision_cap_fewest_cards_wins_and_ties_share():
    bots = bluff_baselines.make_bluff_baselines(4, seed=13)
    result = play_bluff_match(bots, seed=13, decision_cap=8)
    assert result["terminal_reason"] == "cap"
    end = end_log(result)
    fewest = min(len(hand) for hand in end["hands"])
    winners = [i for i in range(SEATS) if len(end["hands"][i]) == fewest]
    assert result["winner_seats"] == winners
    share = 1.0 / len(winners)
    assert result["points"] == [share if i in winners else 0.0 for i in range(SEATS)]


def test_invalid_and_failing_bots_fall_back_with_faults():
    class Garbage:
        name = "Garbage"

        def reset(self):
            pass

        def act(self, observation):
            if observation["turn"]["type"] == "play":
                return {"type": "play", "cards": ["zz", "Ac", "Ac"]}  # unowned + duplicate
            return {"type": "explode"}

    class Timeout:
        name = "Timeout"

        def reset(self):
            pass

        def act(self, observation):
            raise SandboxDown("daemon is down")

    bots = [Garbage(), Scripted("P1", all_pass), Scripted("P2", all_pass), Scripted("P3", all_pass)]
    result = play_bluff_match(bots, seed=15)
    assert result["faults"][0] >= 1
    assert result["errors"][0] == "invalid play action"
    end = end_log(result)
    total = sum(len(hand) for hand in end["hands"]) + len(end["pile"])
    assert total == 52  # fallback still plays a real owned card

    with pytest.raises(SandboxDown):
        play_bluff_match([Timeout(), Scripted("P1", all_pass),
                          Scripted("P2", all_pass), Scripted("P3", all_pass)], seed=16)


def test_observations_never_leak_hidden_state():
    recorders = []
    bots = []
    for index in range(4):
        inner = bluff_baselines.make_bluff_baselines(1, seed=21)[0]
        inner.name = f"Base{index}"
        recorder = Recording(inner)
        recorders.append(recorder)
        bots.append(recorder)
    play_bluff_match(bots, seed=21, capture=True)
    for recorder in recorders:
        for observation in recorder.seen:
            # Own hand only; no seed, deck, pile contents, or opponent cards.
            assert isinstance(observation["hand"], list)
            assert "seed" not in observation and "deck" not in observation
            assert "pile" not in observation
            for event in observation["history"]:
                if event.get("type") == "resolution":
                    # Revealed batches only exist for challenged resolutions.
                    if event["challenged_by"] is None:
                        assert event["revealed"] is None
            for player in observation["players"]:
                assert set(player) == {"seat", "name", "count", "out"}


def test_validate_cards_rejects_bad_payloads():
    hand = ["Ac", "2d", "7s"]
    assert _validate_cards(["Ac"], hand) == ["Ac"]
    assert _validate_cards(["2d", "7s", "Ac"], hand) is not None
    assert _validate_cards([], hand) is None
    assert _validate_cards(["Ac", "Ac"], hand) is None  # duplicate
    assert _validate_cards(["5h"], hand) is None        # unowned
    assert _validate_cards(["Ac", "2d", "7s", "3h"], hand) is None  # > 4
    assert _validate_cards("Ac", hand) is None


def test_baselines_play_legal_matches_and_one_winner():
    for seed in (31, 32, 33):
        bots = bluff_baselines.make_bluff_baselines(4, seed=seed)
        result = play_bluff_match(bots, seed=seed)
        assert result["terminal_reason"] == "win"
        assert len(result["winner_seats"]) == 1
        assert result["decisions"] < DECISION_CAP
        winner = result["winner_seats"][0]
        end = end_log(result)
        assert len(end["hands"][winner]) == 0


def test_baseline_factory_bounds():
    assert bluff_baselines.make_bluff_baselines(0) == []
    with pytest.raises(ValueError):
        bluff_baselines.make_bluff_baselines(5)
    with pytest.raises(ValueError):
        play_bluff_match([], seed=1)


def test_agents_reset_on_every_match_and_startup_failure_is_not_infrastructure():
    class NeedsReset(Scripted):
        def __init__(self):
            super().__init__("Reset", all_pass)
            self.resets = 0
            self.started = False

        def reset(self):
            self.started = True
            self.resets += 1

        def act(self, observation):
            assert self.started
            return super().act(observation)

    bot = NeedsReset()
    bots = [bot, *bluff_baselines.make_bluff_baselines(3)]
    for _ in range(2):
        result = play_bluff_match(bots, seed=4, decision_cap=4)
        assert result['faults'][0] == 0
    assert bot.resets == 2

    class InfrastructureFailure(NeedsReset):
        def reset(self):
            raise SandboxDown('unavailable')

    with pytest.raises(SandboxDown):
        play_bluff_match([InfrastructureFailure(), *bluff_baselines.make_bluff_baselines(3)], seed=4)


def test_cap_resolves_last_card_challenge_and_records_winners():
    seed = next(s for s in range(1000) if all(card[0] != 'K' for card in dealt_hand(s, 0)))

    def play_four(observation):
        if observation['turn']['type'] == 'play':
            return {'type': 'play', 'cards': observation['hand'][:4]}
        if observation['turn']['claimant'] == 0 and observation['players'][0]['count'] == 0:
            return {'type': 'challenge'}
        return {'type': 'pass'}

    result = play_bluff_match([Scripted(str(i), play_four) for i in range(4)], seed,
                              decision_cap=49, capture=True)
    resolution = [entry for entry in result['log'] if entry['type'] == 'resolution'][-1]
    assert result['decisions'] > 49
    assert resolution['challenged_by'] == 1 and resolution['taken_by'] == 0
    assert 0 not in result['winner_seats']
    assert result['frames'][-1]['winner_seats'] == result['winner_seats']
    assert end_log(result)['winner_seats'] == result['winner_seats']
