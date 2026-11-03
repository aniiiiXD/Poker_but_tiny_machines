"""Hearts engine conformance: GAMES_CONTRACT.md §11 + RULES.md invariants."""
import importlib.util
from pathlib import Path

import pytest

from arena.games.common.deck import Deck, standard_deck
from arena.games.hearts import baselines as hb
from arena.games.hearts.engine import (
    HAND_SIZE,
    SEATS,
    TRICK_COUNT,
    legal_plays,
    play_hearts_match,
    score_hand,
    trick_points,
)
from arena.sandbox import SandboxDown

ROOT = Path(__file__).resolve().parents[1]
LOW = {rank: index for index, rank in enumerate("23456789TJQKA")}


def low(card):
    """Independent strength order (2 low, ace high; c < d < h < s)."""
    return (LOW[card[0]], "cdhs".index(card[1]))


def deal_for(seed):
    """Re-derive the engine's private deal from a seed (same deck recipe)."""
    deck = Deck(standard_deck(), seed=seed)
    deck.shuffle()
    return [hand.to_list() for hand in deck.deal(SEATS)]


def rule_legal(observation):
    """Independent re-derivation of the legality rules from RULES.md."""
    hand = observation["hand"]
    trick = [play["card"] for play in observation["trick"]]
    if not trick:
        if observation["trick_number"] == 0:
            return ["2c"] if "2c" in hand else []
        if observation["hearts_broken"]:
            return list(hand)
        return [card for card in hand if card[1] != "h"] or list(hand)
    follow = [card for card in hand if card[1] == trick[0][1]]
    return follow or list(hand)


class Scripted:
    """Observation-only bot following a fixed rule."""

    def __init__(self, name, rule):
        self.name = name
        self._rule = rule

    def reset(self):
        pass

    def act(self, observation):
        return self._rule(observation)


class Recorder:
    """Wraps a bot and records every observation it is handed."""

    def __init__(self, bot):
        self._bot = bot
        self.name = bot.name
        self.observations = []

    def reset(self):
        self.observations = []
        self._bot.reset()

    def act(self, observation):
        self.observations.append(observation)
        return self._bot.act(observation)


def polite(name):
    """Plays the lowest legal card and passes the 3 lowest — observation only."""

    def rule(observation):
        if observation["turn"]["type"] == "pass":
            pool = sorted(observation["hand"], key=low)
            return {"type": "pass", "cards": pool[:3]}
        legal = rule_legal(observation)
        return {"type": "play", "card": min(legal, key=low)}

    return Scripted(name, rule)


def hands_after_pass(result, seed):
    """Per-seat card sets once the simultaneous pass resolves (from the log)."""
    hands = [set(hand) for hand in deal_for(seed)]
    for event in result["log"]:
        if event["type"] == "pass":
            hands[event["seat"]] -= set(event["cards"])
            hands[event["to"]] |= set(event["cards"])
    return hands


def assert_legal_replay(result, seed):
    """Replay the privileged log and assert every settled play was legal."""
    hands = [set(cards) for cards in hands_after_pass(result, seed)]
    plays = [event for event in result["log"] if event["type"] == "play"]
    assert len(plays) == SEATS * HAND_SIZE
    current, previous = [], -1
    broken = False
    for event in plays:
        if event["trick"] != previous:
            current, previous = [], event["trick"]
        observation = {
            "hand": sorted(hands[event["seat"]], key=low),
            "trick": [{"seat": seat, "card": card} for seat, card in current],
            "hearts_broken": broken,
            "trick_number": event["trick"],
        }
        legal = rule_legal(observation)
        assert event["card"] in legal
        if event["fault"]:
            assert event["card"] == min(legal, key=low)  # fallback: lowest legal
        hands[event["seat"]].remove(event["card"])
        current.append((event["seat"], event["card"]))
        if event["card"][1] == "h":
            assert event["hearts_broken"]  # a heart either broke hearts or found them broken
            broken = True
        else:
            assert broken == event["hearts_broken"]
    assert all(not hand for hand in hands)  # the hand exhausts exactly


def test_seat_count_is_enforced():
    with pytest.raises(ValueError):
        play_hearts_match([polite(str(i)) for i in range(SEATS - 1)], seed=1)
    with pytest.raises(ValueError):
        play_hearts_match([polite(str(i)) for i in range(SEATS + 1)], seed=1)


def test_match_is_deterministic_per_seed():
    keys = ("points", "match_points", "winner_seats", "terminal_reason", "faults",
            "errors", "decisions", "names", "log", "frames")
    a = play_hearts_match(hb.make_hearts_baselines(4, seed=7), seed=7, capture=True)
    b = play_hearts_match(hb.make_hearts_baselines(4, seed=7), seed=7, capture=True)
    for key in keys:
        assert a[key] == b[key]
    other = play_hearts_match(hb.make_hearts_baselines(4, seed=8), seed=8, capture=True)
    assert other["frames"] != a["frames"]  # a new seed really reshuffles


def test_deal_is_13x4_and_conserves_52_cards():
    result = play_hearts_match([polite(str(i)) for i in range(SEATS)], seed=3, capture=True)
    deal = deal_for(3)
    assert [len(hand) for hand in deal] == [HAND_SIZE] * SEATS
    assert sorted(card for hand in deal for card in hand) == sorted(standard_deck())
    deal_entry = next(event for event in result["log"] if event["type"] == "deal")
    assert [sorted(hand) for hand in deal_entry["hands"]] == [sorted(hand) for hand in deal]
    play_frames = [f for f in result["frames"] if f["kind"] == "play"]
    assert len(play_frames) == 52
    assert sorted(f["card"] for f in play_frames) == sorted(standard_deck())
    for seat in range(SEATS):
        assert sum(1 for f in play_frames if f["seat"] == seat) == HAND_SIZE


def test_pass_rotation_all_seats_receive_exactly_three():
    seed = 5
    recorded = [Recorder(bot) for bot in hb.make_hearts_baselines(4, seed=seed)]
    result = play_hearts_match(recorded, seed=seed, capture=True)
    passes = [event for event in result["log"] if event["type"] == "pass"]
    assert len(passes) == SEATS
    for event in passes:
        assert len(event["cards"]) == 3
        assert len(set(event["cards"])) == 3
        assert event["to"] == (event["seat"] + 1) % SEATS  # single match: pass left
    deal = deal_for(seed)
    for seat in range(SEATS):
        gave = next(event["cards"] for event in passes if event["seat"] == seat)
        got = next(event["cards"] for event in passes if event["to"] == seat)
        first_play = next(obs for obs in recorded[seat].observations
                          if obs["turn"]["type"] == "play")
        assert len(first_play["hand"]) == HAND_SIZE
        assert set(first_play["hand"]) == (set(deal[seat]) - set(gave)) | set(got)
        seen = [obs for obs in recorded[seat].observations if obs["received"] is not None]
        assert seen and all(obs["received"] == got for obs in seen)


def test_two_of_clubs_opens_and_is_enforced():
    seed = 9

    def bad_opener(observation):
        if observation["turn"]["type"] == "pass":
            return {"type": "pass", "cards": sorted(observation["hand"], key=low)[:3]}
        legal = rule_legal(observation)
        if observation["trick_number"] == 0 and not observation["trick"]:
            sneaky = [card for card in observation["hand"] if card != "2c"]
            return {"type": "play", "card": sneaky[0]}  # always an illegal opening
        return {"type": "play", "card": min(legal, key=low)}

    bots = [Scripted(f"bad{i}", bad_opener) for i in range(SEATS)]
    result = play_hearts_match(bots, seed=seed, capture=True)
    holder = next(seat for seat in range(SEATS)
                  if "2c" in hands_after_pass(result, seed)[seat])
    first_play = next(f for f in result["frames"] if f["kind"] == "play")
    assert first_play["seat"] == holder and first_play["card"] == "2c"
    assert result["faults"][holder] >= 1
    assert sum(result["faults"]) == 1  # only the opening attempt was rejected


def test_illegal_follow_suit_is_rejected_to_fallback():
    seed = 4

    def stubborn(observation):
        if observation["turn"]["type"] == "pass":
            return {"type": "pass", "cards": sorted(observation["hand"], key=low)[:3]}
        trick = observation["trick"]
        legal = rule_legal(observation)
        if trick:
            led = trick[0]["card"][1]
            offsuit = [card for card in observation["hand"] if card[1] != led]
            if offsuit:  # holds the led suit but tries to slough anyway
                return {"type": "play", "card": min(offsuit, key=low)}
        return {"type": "play", "card": min(legal, key=low)}

    bots = [Scripted(f"stubborn{i}", stubborn) for i in range(SEATS)]
    result = play_hearts_match(bots, seed=seed, capture=True)
    assert sum(result["faults"]) > 0
    assert all(error for error in result["errors"])
    assert_legal_replay(result, seed)  # every settled play is legal anyway


def test_hearts_cannot_lead_until_broken():
    hand = ["2h", "9h", "5s", "Ac"]
    assert legal_plays(hand, [], False, 5) == ["5s", "Ac"]
    assert set(legal_plays(hand, [], True, 5)) == set(hand)
    # an all-hearts hand may lead hearts (RULES.md C3)
    assert legal_plays(["2h", "9h"], [], False, 5) == ["2h", "9h"]
    # the Q♠ is a spade: leading it does not need broken hearts (C1)
    assert set(legal_plays(["Qs", "3d"], [], False, 5)) == {"Qs", "3d"}
    # follow suit beats the break rule: hearts led, hearts must be followed
    assert legal_plays(["2c", "5h"], ["3h"], True, 4) == ["5h"]
    # void in the led suit: any discard, penalty cards included
    assert set(legal_plays(["2h", "Qs"], ["3c"], False, 0)) == {"2h", "Qs"}
    # the opening lead is the 2♣ and nothing else (C2)
    assert legal_plays(["2c", "Ah", "Qs"], [], False, 0) == ["2c"]


def test_trick_points_and_moon_scoring_are_exact():
    assert trick_points(["2c", "3d", "4s", "5h"]) == 1
    assert trick_points(["2h", "3h", "Qs", "Ac"]) == 15
    assert trick_points(["Ah", "Kh", "Qh", "Jh"]) == 4
    assert trick_points(["2c", "3d", "4s", "5c"]) == 0
    assert score_hand([26, 0, 0, 0]) == [0, 26, 26, 26]
    assert score_hand([0, 0, 26, 0]) == [26, 26, 0, 26]
    assert score_hand([13, 13, 0, 0]) == [13, 13, 0, 0]
    assert score_hand([7, 6, 8, 5]) == [7, 6, 8, 5]


def test_result_points_match_the_public_trick_record():
    for seed in (11, 12, 13):
        result = play_hearts_match(hb.make_hearts_baselines(4, seed=seed), seed=seed,
                                   capture=True)
        tally = [0] * SEATS
        for frame in result["frames"]:
            if frame["kind"] == "trick":
                tally[frame["winner"]] += frame["points"]
        assert result["points"] == score_hand(tally)
        total = sum(result["points"])
        assert total == 26 or (total == 78 and tally.count(26) == 1)  # moon payout
        assert result["winner_seats"] and sum(result["match_points"]) == pytest.approx(1.0)


def test_trick_winner_leads_the_next_trick():
    seed = 21
    result = play_hearts_match(hb.make_hearts_baselines(4, seed=seed), seed=seed, capture=True)
    first_lead, winners = {}, {}
    for frame in result["frames"]:
        if frame["kind"] == "play":
            first_lead.setdefault(frame["trick"], frame["seat"])
        elif frame["kind"] == "trick":
            winners[frame["trick"]] = frame["winner"]
    assert len(winners) == TRICK_COUNT
    holder = next(seat for seat in range(SEATS)
                  if "2c" in hands_after_pass(result, seed)[seat])
    assert first_lead[0] == holder
    for trick in range(TRICK_COUNT - 1):
        assert first_lead[trick + 1] == winners[trick]


def test_game_ends_after_exactly_13_tricks_without_cap():
    result = play_hearts_match([polite(str(i)) for i in range(SEATS)], seed=2, capture=True)
    assert result["terminal_reason"] == "win"
    assert result["hands"] == 1 and result["matches"] == 1
    assert result["decisions"] == SEATS + SEATS * TRICK_COUNT == 56
    assert len([f for f in result["frames"] if f["kind"] == "trick"]) == TRICK_COUNT
    end = result["frames"][-1]
    assert end["kind"] == "end" and end["counts"] == [0, 0, 0, 0]
    assert result["winner_seats"] and sum(result["match_points"]) == pytest.approx(1.0)
    assert_legal_replay(result, 2)


def test_decision_cap_safety_scores_by_fewest_points():
    # cap = 4 lets the four pass decisions through, then the safety net fires.
    result = play_hearts_match([polite(str(i)) for i in range(SEATS)], seed=2, decision_cap=4)
    assert result["terminal_reason"] == "cap"
    assert result["points"] == [0, 0, 0, 0]
    assert result["winner_seats"] == [0, 1, 2, 3]
    assert all(points == 0.25 for points in result["match_points"])


def test_garbage_bots_fall_back_and_finish():
    def garbage(observation):
        if observation["turn"]["type"] == "pass":
            return {"type": "pass", "cards": ["nope", "2c", "2c", "9x"]}
        return {"type": "banana"}

    class Crasher:
        name = "crasher"

        def reset(self):
            pass

        def act(self, observation):
            raise RuntimeError("boom")

    bots = [
        Scripted("garbage0", garbage),
        Crasher(),
        Scripted("garbage2", lambda obs: {"type": "play", "card": "Xx"}),
        Scripted("garbage3", lambda obs: "pass please"),
    ]
    result = play_hearts_match(bots, seed=6, capture=True)
    assert result["terminal_reason"] == "win"
    assert result["faults"] == [14, 14, 14, 14]  # every decision faulted and fell back
    assert all(error for error in result["errors"])
    assert len([f for f in result["frames"] if f["kind"] == "trick"]) == TRICK_COUNT
    assert sorted(f["card"] for f in result["frames"] if f["kind"] == "play") == \
        sorted(standard_deck())
    assert result["winner_seats"] and sum(result["match_points"]) == pytest.approx(1.0)
    assert_legal_replay(result, 6)  # the fallbacks themselves are legal play


def test_observations_never_leak_hidden_state():
    seed = 17
    recorded = [Recorder(bot) for bot in hb.make_hearts_baselines(4, seed=seed)]
    result = play_hearts_match(recorded, seed=seed, capture=True)
    deal = deal_for(seed)
    allowed = hands_after_pass(result, seed)
    received_expected = {}
    for event in result["log"]:
        if event["type"] == "pass":
            received_expected[event["to"]] = event["cards"]
    public_cards = set()
    plays_by_trick = {}
    for frame in result["frames"]:
        if frame["kind"] == "play":
            public_cards.add(frame["card"])
            plays_by_trick.setdefault(frame["trick"], []).append((frame["seat"], frame["card"]))
        elif frame["kind"] == "trick":
            public_cards |= {play["card"] for play in frame["cards"]}
    for seat in range(SEATS):
        for obs in recorded[seat].observations:
            assert obs["seat"] == seat
            assert "seed" not in obs and "log" not in obs and "hands" not in obs
            assert len(set(obs["hand"])) == len(obs["hand"])
            for player in obs["players"]:
                assert set(player) == {"seat", "name", "count", "taken"}
            if obs["turn"]["type"] == "pass":
                # pre-reveal: exactly the dealt hand, nothing received yet
                assert set(obs["hand"]) == set(deal[seat])
                assert obs["received"] is None
            else:
                assert set(obs["hand"]) <= allowed[seat]
                assert obs["received"] == received_expected[seat]
                prefix = plays_by_trick[obs["trick_number"]][: len(obs["trick"])]
                assert [(p["seat"], p["card"]) for p in obs["trick"]] == prefix
            for play in obs["trick"]:
                assert play["card"] in public_cards
            for trick in obs["tricks"]:
                for play in trick["cards"]:
                    assert play["card"] in public_cards


def test_public_replay_wrapper_carries_no_hidden_cards():
    result = play_hearts_match(hb.make_hearts_baselines(4, seed=31), seed=31, capture=True)
    replay = {"game": "hearts", "protocol": 1, "names": result["names"],
              "frames": result["frames"]}
    assert replay["game"] == "hearts" and replay["protocol"] == 1
    pass_frames = [f for f in replay["frames"] if f["kind"] == "pass"]
    assert len(pass_frames) == SEATS
    assert all(set(f) == {"kind", "counts", "seat"} for f in pass_frames)
    play_frames = [f for f in replay["frames"] if f["kind"] == "play"]
    assert len(play_frames) == 52
    for frame in (f for f in replay["frames"] if f["kind"] == "trick"):
        assert 0 <= frame["points"] <= 26 and frame["winner"] in range(SEATS)
        assert len(frame["cards"]) == SEATS
    assert replay["frames"][-1]["kind"] == "end"
    assert "hand" not in str(sorted(replay["frames"][-1].keys()))


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 42])
def test_baselines_complete_full_matches(seed):
    result = play_hearts_match(hb.make_hearts_baselines(4, seed=seed), seed=seed, capture=True)
    tricks = [f for f in result["frames"] if f["kind"] == "trick"]
    assert len(tricks) == TRICK_COUNT  # exactly one trick-winner sequence
    assert len({f["trick"] for f in tricks}) == TRICK_COUNT
    assert all(f["winner"] in range(SEATS) for f in tricks)
    assert result["terminal_reason"] == "win"
    assert result["winner_seats"]  # at least one winner seat
    assert result["faults"] == [0, 0, 0, 0]
    assert result["decisions"] == 56
    assert sum(result["match_points"]) == pytest.approx(1.0)
    assert_legal_replay(result, seed)


def test_baseline_factory_shapes():
    bots = hb.make_hearts_baselines(4, seed=0)
    assert [type(bot).__name__ for bot in bots] == \
        ["SafeDumper", "MoonHunter", "QsDodger", "LowCardFloater"]
    assert [bot.name for bot in bots] == ["Dumper", "MoonHunter", "Dodger", "Floater"]
    with pytest.raises(ValueError):
        hb.make_hearts_baselines(5)
    with pytest.raises(ValueError):
        hb.make_hearts_baselines(-1)


def test_sandbox_down_propagates_from_reset_and_act():
    class DownOnReset:
        name = "down-reset"

        def reset(self):
            raise SandboxDown("daemon gone")

        def act(self, observation):
            raise AssertionError("unreachable")

    class DownOnAct:
        name = "down-act"

        def reset(self):
            pass

        def act(self, observation):
            raise SandboxDown("daemon gone mid-hand")

    with pytest.raises(SandboxDown):
        play_hearts_match([DownOnReset(), *hb.make_hearts_baselines(3, seed=1)], seed=1)
    with pytest.raises(SandboxDown):
        play_hearts_match([DownOnAct(), *hb.make_hearts_baselines(3, seed=1)], seed=1)


def _load_agent(path):
    spec = importlib.util.spec_from_file_location(path.stem + "_" + path.parent.name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.Agent()


def test_starter_agent_plays_a_legal_match():
    bots = [_load_agent(ROOT / "starter-hearts" / "agent.py"),
            *hb.make_hearts_baselines(3, seed=3)]
    result = play_hearts_match(bots, seed=3, capture=True)
    assert result["terminal_reason"] == "win"
    assert result["faults"][0] == 0
    assert_legal_replay(result, 3)


def test_starter_model_agent_plays_a_legal_match():
    pytest.importorskip("numpy")  # the host venv has no numpy; the model image does
    bots = [_load_agent(ROOT / "starter-model-hearts" / "agent.py"),
            *hb.make_hearts_baselines(3, seed=3)]
    result = play_hearts_match(bots, seed=3, capture=True)
    assert result["terminal_reason"] == "win"
    assert result["faults"][0] == 0
    assert_legal_replay(result, 3)
