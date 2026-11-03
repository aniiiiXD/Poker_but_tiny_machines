"""Stack Theory Rummy v1 engine rules, determinism, privacy, and fallbacks."""
import json

import pytest

from arena.games.rummy import baselines as rummy_baselines
from arena.games.rummy.engine import (
    DECISION_CAP,
    GAME_ID,
    HAND_SIZE,
    JOKERS_PER_MELD,
    PROTOCOL,
    RULES_VERSION,
    SEATS,
    WRONG_DECLARE_PENALTY,
    _validate_declare,
    _validate_discard,
    _validate_draw,
    card_points,
    classify_meld,
    find_groups,
    hand_deadwood,
    play_rummy_match,
    sort_key,
    valid_declaration,
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


def draw_stock(observation):
    return {"type": "draw", "from": "stock" if observation["stock_remaining"] else "discard"}


def declare_when_valid(observation):
    if observation["turn"]["type"] == "declare":
        return {"type": "declare", "hand": list(observation["hand"])}
    if observation["turn"]["type"] == "discard":
        return {"type": "discard", "card": min(observation["hand"], key=sort_key)}
    return draw_stock(observation)


def never_declare(observation):
    if observation["turn"]["type"] == "declare":
        return {"type": "pass"}
    return declare_when_valid(observation)


def always_stock(observation):
    """Draws from the stock even when the observation says it is empty, so the
    reshuffle path is exercised."""
    if observation["turn"]["type"] == "declare":
        return {"type": "pass"}
    if observation["turn"]["type"] == "discard":
        return {"type": "discard", "card": min(observation["hand"], key=sort_key)}
    return {"type": "draw", "from": "stock"}


def end_log(result):
    return next(entry for entry in result["log"] if entry["type"] == "end")


def deal_log(result):
    return result["log"][0]


def replay_frames(result):
    return result["frames"]["frames"]


def test_deterministic_replay_from_seed_and_bots():
    bots = rummy_baselines.make_rummy_baselines(4, seed=99)
    first = play_rummy_match(bots, seed=123, capture=True)
    bots2 = rummy_baselines.make_rummy_baselines(4, seed=99)
    second = play_rummy_match(bots2, seed=123, capture=True)
    assert first["points"] == second["points"]
    assert first["decisions"] == second["decisions"]
    assert first["winner_seats"] == second["winner_seats"]
    assert [e["type"] for e in first["log"]] == [e["type"] for e in second["log"]]
    assert first["frames"] == second["frames"]


def test_different_seed_deals_different_hands():
    a = deal_log(play_rummy_match(rummy_baselines.make_rummy_baselines(2, seed=1), seed=1))
    b = deal_log(play_rummy_match(rummy_baselines.make_rummy_baselines(2, seed=2), seed=2))
    assert a["hands"] != b["hands"]


def test_result_schema_and_wrapped_frames():
    result = play_rummy_match(
        rummy_baselines.make_rummy_baselines(2, seed=3), seed=3, capture=True,
    )
    assert set(result) == {
        "points", "winner_seats", "terminal_reason", "faults", "errors",
        "hands", "matches", "decisions", "names", "log", "frames",
    }
    assert result["hands"] == 1 and result["matches"] == 1
    frames = result["frames"]
    assert set(frames) == {"game", "protocol", "names", "frames"}
    assert frames["game"] == GAME_ID and frames["protocol"] == PROTOCOL
    assert frames["names"] == result["names"]
    assert replay_frames(result)[-1]["kind"] == "end"
    for frame in replay_frames(result):
        assert len(frame["counts"]) == 2
    json.dumps(result["frames"])  # replay frames are plain JSON


def test_shoe_is_two_decks_plus_two_printed_jokers():
    result = play_rummy_match(rummy_baselines.make_rummy_baselines(4, seed=5), seed=5)
    end = end_log(result)
    every = [
        card for hand in end["hands"] for card in hand
    ] + end["stock"] + end["discard"]
    assert len(every) == 106
    natural = [card for card in every if card not in ("XJ1", "XJ2")]
    assert every.count("XJ1") == 1 and every.count("XJ2") == 1
    assert len(set(natural)) == 52  # each natural card exists exactly twice
    assert all(natural.count(card) == 2 for card in set(natural))


def test_deal_thirteen_cards_per_seat_for_two_four_and_six_seats():
    for seats in (2, 4, 6):
        result = play_rummy_match(rummy_baselines.make_rummy_baselines(seats, seed=7), seed=7)
        deal = deal_log(result)
        assert [len(hand) for hand in deal["hands"]] == [HAND_SIZE] * seats
        assert len(deal["stock"]) == 106 - seats * HAND_SIZE - 1  # minus the upcard
        assert len(deal["discard"]) == 1
        assert deal["wild_rank"] in "A23456789TJQK"
        end = end_log(result)
        total = sum(len(hand) for hand in end["hands"]) + len(end["stock"]) + len(end["discard"])
        assert total == 106


def test_seats_validation():
    with pytest.raises(ValueError):
        play_rummy_match([], seed=1)
    with pytest.raises(ValueError):
        play_rummy_match(rummy_baselines.make_rummy_baselines(2, seed=1)[:1], seed=1)
    with pytest.raises(ValueError):
        play_rummy_match(list(rummy_baselines.make_rummy_baselines(6, seed=1)) + [object()], seed=1)


# ---------------------------------------------------------------------------
# meld validator
# ---------------------------------------------------------------------------

def test_pure_sequences():
    assert classify_meld(["3h", "4h", "5h"], "9") == "pure"
    assert classify_meld(["Ah", "2h", "3h"], "9") == "pure"  # ace low
    assert classify_meld(["Qh", "Kh", "Ah"], "9") == "pure"  # ace high
    assert classify_meld(["Th", "Jh", "Qh", "Kh"], "9") == "pure"
    assert classify_meld(["Kh", "Ah", "2h"], "9") is None  # K-A-2 wraps: never
    assert classify_meld(["3h", "4h", "6h"], "9") is None  # gap, no joker
    assert classify_meld(["3h", "4h", "5d"], "9") is None  # mixed suits
    assert classify_meld(["3h", "4h"], "9") is None  # too short


def test_impure_sequences_with_jokers():
    assert classify_meld(["3h", "4h", "XJ1"], "9") == "impure"
    assert classify_meld(["3h", "4h", "5h", "XJ1"], "9") == "impure"
    assert classify_meld(["3h", "5h", "7h", "XJ1", "XJ2"], "9") == "impure"
    assert classify_meld(["3h", "5h", "7h", "XJ1"], "9") is None  # two gaps, one joker
    # the maximum two jokers per meld (RULES.md joker cap)
    assert JOKERS_PER_MELD == 2
    assert classify_meld(["3h", "4h", "5h", "XJ1", "XJ2"], "9") == "impure"


def test_wild_rank_cards_are_jokers_and_never_pure():
    assert classify_meld(["6h", "7h", "8h"], "9") == "pure"
    assert classify_meld(["6h", "7h", "8h"], "7") == "impure"  # 7h is the wild joker
    assert classify_meld(["5c", "5d", "5h"], "5") is None  # all three are jokers now


def test_sets():
    assert classify_meld(["5c", "5d", "5h"], "9") == "set"
    assert classify_meld(["5c", "5d", "5h", "5s"], "9") == "set"
    assert classify_meld(["5c", "5d", "XJ1"], "9") == "set"
    assert classify_meld(["5c", "XJ1", "XJ2"], "9") == "set"
    assert classify_meld(["5c", "5c", "5d"], "9") is None  # duplicate card ID
    assert classify_meld(["5c", "5d", "5h", "5s", "XJ1"], "9") is None  # sets are 3-4
    assert classify_meld(["5c", "5d", "6d"], "9") is None  # not one rank, not one suit


def test_find_groups_partitions_and_declaration_shape():
    good = ["3h", "4h", "5h", "6h", "7h", "8h", "9h", "Th",
            "3s", "4s", "5s", "9c", "9d", "9s"]
    groups = valid_declaration(good, "2")
    assert groups is not None
    assert sorted(card for group in groups for card in group) == sorted(good)

    broken = ["3h", "4h", "5h", "6h", "7h", "8h", "9h", "Th",
              "3s", "4s", "5s", "9c", "9d", "Kc"]
    assert valid_declaration(broken, "2") is None

    one_sequence = ["3h", "4h", "5h", "6h", "7h", "9c", "9d", "9s",
                    "Tc", "Td", "Th", "Jc", "Jd", "Js"]
    assert find_groups(one_sequence, "2") is not None  # it partitions...
    assert valid_declaration(one_sequence, "2") is None  # ...but needs two sequences


def test_declaration_with_wild_rank_substitution():
    hand = ["3h", "4h", "5c", "6h", "7h",  # 5c (wild) fills the 5h gap
            "9s", "Ts", "Js", "9c", "9d", "9h", "Tc", "Td", "Th"]
    groups = valid_declaration(hand, "5")
    assert groups is not None
    kinds = [classify_meld(group, "5") for group in groups]
    assert "impure" in kinds and "pure" in kinds

    # three jokers forced into one meld bust the per-meld cap: the two 4-card
    # sets cannot absorb them and 3h-4h can only bridge with two
    forced = ["3h", "4h", "5c", "5d", "5h", "5s",
              "9c", "9d", "9h", "9s", "Tc", "Td", "Th", "Ts"]
    assert valid_declaration(forced, "5") is None


def test_card_points():
    assert card_points("XJ1", "2") == 0
    assert card_points("2c", "9") == 2
    assert card_points("Tc", "9") == 10
    assert card_points("Ac", "9") == 10
    assert card_points("Kd", "9") == 10
    assert card_points("7h", "7") == 0  # the wild rank scores nothing


def test_deadwood_at_cap():
    declarable = ["3h", "4h", "5h", "6h", "7h", "8h", "9h", "Th",
                  "3s", "4s", "5s", "9c", "9d", "9s"]
    assert hand_deadwood(declarable, "2") == 0
    assert hand_deadwood(["3h", "4h", "5h"], "2") == 12  # one sequence is not a show
    assert hand_deadwood(["3h", "Kh", "XJ1"], "2") == 13


def test_action_validators():
    assert _validate_draw({"type": "draw", "from": "stock"}) == {"type": "draw", "from": "stock"}
    assert _validate_draw({"type": "draw", "from": "middle"}) is None
    assert _validate_draw({"type": "explode"}) is None
    assert _validate_draw("draw") is None

    hand_cards = ["3h", "4h", "9s"]
    assert _validate_discard({"type": "discard", "card": "9s"}, hand_cards) == {
        "type": "discard", "card": "9s",
    }
    assert _validate_discard({"type": "discard", "card": "5h"}, hand_cards) is None
    assert _validate_discard({"type": "pass"}, hand_cards) is None

    class FakeHand:
        def to_list(self):
            return ["3h", "4h", "5h", "6h", "7h", "8h", "9h", "Th",
                    "3s", "4s", "5s", "9c", "9d", "9s"]

    fake = FakeHand()
    shown = fake.to_list()
    assert _validate_declare({"type": "pass"}, fake) == {"type": "pass"}
    assert _validate_declare({"type": "declare", "hand": list(reversed(shown))}, fake) == {
        "type": "declare", "hand": list(reversed(shown)),
    }
    assert _validate_declare({"type": "declare", "hand": shown[:13]}, fake) is None
    assert _validate_declare({"type": "declare", "hand": ["3h", "4h"]}, fake) is None
    assert _validate_declare({"type": "declare", "hand": ["zz"] + shown[1:]}, fake) is None
    assert _validate_declare({"type": "explode"}, fake) is None


def test_declare_turn_only_reached_at_fourteen_cards():
    recorder = Recording(Scripted("W", never_declare))
    play_rummy_match([recorder, *rummy_baselines.make_rummy_baselines(1, seed=11)], seed=11)
    for observation in recorder.seen:
        if observation["turn"]["type"] == "declare":
            assert len(observation["hand"]) == HAND_SIZE + 1
        else:
            assert len(observation["hand"]) in (HAND_SIZE, HAND_SIZE + 1)


def test_valid_declaration_wins_immediately():
    seed = next(
        s for s in range(400)
        if play_rummy_match(rummy_baselines.make_rummy_baselines(2, seed=s), seed=s)[
            "terminal_reason"] == "win"
    )
    result = play_rummy_match(
        rummy_baselines.make_rummy_baselines(2, seed=seed), seed=seed, capture=True,
    )
    assert result["terminal_reason"] == "win"
    assert len(result["winner_seats"]) == 1
    winner = result["winner_seats"][0]
    share = 1.0
    assert result["points"] == [share if i == winner else 0.0 for i in range(2)]
    declaration = next(e for e in result["log"] if e["type"] == "declaration")
    assert declaration["seat"] == winner
    assert len(declaration["hand"]) == HAND_SIZE + 1
    kinds = [classify_meld(group, deal_log(result)["wild_rank"])
             for group in declaration["groups"]]
    assert kinds.count("set") <= len(kinds) - 2
    frame = next(f for f in replay_frames(result) if f["kind"] == "declaration")
    assert frame["seat"] == winner and frame["groups"] == declaration["groups"]
    assert replay_frames(result)[-1]["kind"] == "end"


def test_wrong_declaration_penalizes_and_reveals_publicly():
    calls = {"declares": 0}

    def always_declares(observation):
        if observation["turn"]["type"] == "declare":
            calls["declares"] += 1
            return {"type": "declare", "hand": list(observation["hand"])}
        if observation["turn"]["type"] == "discard":
            return {"type": "discard", "card": min(observation["hand"], key=sort_key)}
        return draw_stock(observation)

    witness = Recording(Scripted("Witness", never_declare))
    bots = [Scripted("Showoff", always_declares), witness]
    result = play_rummy_match(bots, seed=17, decision_cap=8)
    assert calls["declares"] >= 1
    wrong = [e for e in result["log"] if e["type"] == "wrong_declaration"]
    assert wrong, "a 14-card non-melding hand must be a wrong declaration"
    assert result["faults"][0] >= len(wrong)
    assert result["errors"][0] == "wrong declaration"
    # the show is public: the witness saw the hand in its history
    reveals = [
        event for observation in witness.seen for event in observation["history"]
        if event["type"] == "wrong_declaration"
    ]
    assert reveals and all(len(event["hand"]) == HAND_SIZE + 1 for event in reveals)
    # and the penalties land on the seat's cap deadwood
    end = end_log(result)
    if result["terminal_reason"] == "cap":
        expected = [
            hand_deadwood(hand, end["wild_rank"]) + WRONG_DECLARE_PENALTY * shows
            for hand, shows in zip(end["hands"], end["wrong_shows"])
        ]
        assert end["deadwood"] == expected
        lowest = min(expected)
        assert result["winner_seats"] == [
            i for i, value in enumerate(expected) if value == lowest
        ]


def test_malformed_declare_is_a_plain_fault_without_penalty():
    def bad_payload(observation):
        if observation["turn"]["type"] == "declare":
            return {"type": "declare", "hand": observation["hand"][:13]}
        if observation["turn"]["type"] == "discard":
            return {"type": "discard", "card": min(observation["hand"], key=sort_key)}
        return draw_stock(observation)

    result = play_rummy_match(
        [Scripted("Bad", bad_payload), Scripted("Ok", never_declare)], seed=19,
        decision_cap=6,
    )
    assert result["faults"][0] >= 1
    assert result["errors"][0] == "invalid declare action"
    end = end_log(result)
    assert end["wrong_shows"] == [0, 0]
    assert not [e for e in result["log"] if e["type"] == "wrong_declaration"]


def test_discard_must_be_owned_and_public_top_tracks_the_pile():
    recorder = Recording(Scripted("W", never_declare))
    result = play_rummy_match(
        [recorder, *rummy_baselines.make_rummy_baselines(2, seed=23)], seed=23,
    )
    assert result["faults"] == [0, 0, 0]
    # Rebuild the true public pile from the privileged log and check every
    # observation's discard_top / discard_size against it.
    upcard = deal_log(result)["discard"][0]
    public = [e for e in result["log"] if e["type"] in (
        "draw", "discard", "reshuffle", "wrong_declaration")]
    states = [(upcard, 1)]
    for entry in public:
        if entry["type"] == "draw":
            after = entry["discard"]
            states.append((after[-1] if after else None, len(after)))
        elif entry["type"] == "discard":
            states.append((entry["card"], states[-1][1] + 1))
        elif entry["type"] == "reshuffle":
            states.append((states[-1][0], 1))
        else:
            states.append(states[-1])
    for observation in recorder.seen:
        top, size = states[len(observation["history"])]
        assert observation["discard_top"] == top
        assert observation["discard_size"] == size


def test_stock_exhaustion_reshuffles_discards_except_top():
    result = play_rummy_match(
        [Scripted(f"Draw{i}", always_stock) for i in range(2)], seed=29,
    )
    reshuffles = [e for e in result["log"] if e["type"] == "reshuffle"]
    assert reshuffles, "a blind stock draw on an empty stock must reshuffle"
    end = end_log(result)
    total = sum(len(hand) for hand in end["hands"]) + len(end["stock"]) + len(end["discard"])
    assert total == 106
    for entry in reshuffles:
        # Walk the privileged log to reconstruct the exact pile at the moment
        # of the reshuffle: draw entries snapshot the pile, discard events grow it.
        index = result["log"].index(entry)
        pile = list(deal_log(result)["discard"])
        for walk in result["log"][1:index]:
            if walk["type"] == "draw":
                pile = list(walk["discard"])
            elif walk["type"] == "discard":
                pile.append(walk["card"])
        top = pile[-1]
        # everything except the public top card moves into the new stock —
        # as a multiset, since two decks share card IDs
        assert entry["moved"] and sorted(entry["moved"] + [top]) == sorted(pile)
        # the top card stays exactly where it was: alone on the pile
        following = next(e for e in result["log"][index + 1:] if "discard" in e)
        assert following["discard"] == [top]
    # reshuffles are public knowledge in the observations' history
    observer = Recording(Scripted("W", always_stock))
    play_rummy_match([observer, Scripted("D2", always_stock)], seed=29)
    events = [e for o in observer.seen for e in o["history"] if e["type"] == "reshuffle"]
    assert events
    for event in events:
        assert set(event) == {"type", "moved"}  # a count, never the card order


def test_cap_lowest_deadwood_wins_and_ties_share():
    decisive = tied = None
    for seed in range(500):
        result = play_rummy_match(
            rummy_baselines.make_rummy_baselines(2, seed=seed), seed=seed,
            decision_cap=2,
        )
        assert result["terminal_reason"] == "cap"
        end = end_log(result)
        expected = [
            hand_deadwood(hand, end["wild_rank"]) + WRONG_DECLARE_PENALTY * shows
            for hand, shows in zip(end["hands"], end["wrong_shows"])
        ]
        lowest = min(expected)
        winners = [i for i, value in enumerate(expected) if value == lowest]
        assert result["winner_seats"] == winners
        assert result["points"] == [
            1.0 / len(winners) if i in winners else 0.0 for i in range(2)
        ]
        if len(winners) == 1:
            decisive = seed
        else:
            tied = seed
        if decisive is not None and tied is not None:
            break
    assert decisive is not None and tied is not None


def test_cap_cuts_at_a_thirteen_card_boundary():
    result = play_rummy_match(
        rummy_baselines.make_rummy_baselines(2, seed=31), seed=31, decision_cap=2,
    )
    assert result["terminal_reason"] == "cap"
    end = end_log(result)
    assert all(len(hand) == HAND_SIZE for hand in end["hands"])


def test_garbage_bot_faults_fall_back_deterministically():
    class Garbage:
        name = "Garbage"

        def reset(self):
            pass

        def act(self, observation):
            turn = observation["turn"]["type"]
            if turn == "draw":
                return {"type": "draw", "from": "middle"}
            if turn == "declare":
                return {"type": "explode"}
            return {"type": "discard", "card": "zz"}

    result = play_rummy_match([Garbage(), Scripted("Ok", never_declare)], seed=33)
    assert result["faults"][0] >= 3
    assert result["errors"][0] == "invalid draw action"
    end = end_log(result)
    total = sum(len(hand) for hand in end["hands"]) + len(end["stock"]) + len(end["discard"])
    assert total == 106  # every fallback still moved real cards


def test_crashing_bots_fall_back_and_sandbox_down_propagates():
    class Crasher:
        name = "Crasher"

        def reset(self):
            pass

        def act(self, observation):
            raise RuntimeError("boom")

    result = play_rummy_match([Crasher(), Scripted("Ok", never_declare)], seed=35,
                              decision_cap=10)
    assert result["faults"][0] >= 1
    assert "boom" in result["errors"][0]

    class Downed:
        name = "Downed"

        def reset(self):
            pass

        def act(self, observation):
            raise SandboxDown("daemon is down")

    with pytest.raises(SandboxDown):
        play_rummy_match([Downed(), Scripted("Ok", never_declare)], seed=36)

    class DownedReset(Downed):
        def reset(self):
            raise SandboxDown("unavailable at reset")

    with pytest.raises(SandboxDown):
        play_rummy_match([DownedReset(), Scripted("Ok", never_declare)], seed=37)


def test_reset_failure_faults_once_then_falls_back():
    class NeedsReset:
        name = "Reset"

        def __init__(self):
            self.started = False

        def reset(self):
            self.started = True

        def act(self, observation):
            assert self.started
            return never_declare(observation)

    bot = NeedsReset()
    result = play_rummy_match([bot, Scripted("Ok", never_declare)], seed=39,
                              decision_cap=10)
    assert result["faults"] == [0, 0]

    class BrokenReset(NeedsReset):
        def reset(self):
            raise RuntimeError("no table")

    broken = BrokenReset()
    result = play_rummy_match([broken, Scripted("Ok", never_declare)], seed=40,
                              decision_cap=10)
    assert result["faults"][0] >= 1  # counted once at reset
    faults_before = result["faults"][0]
    result2 = play_rummy_match([broken, Scripted("Ok", never_declare)], seed=41,
                               decision_cap=4)
    assert result2["faults"][0] >= faults_before  # fallbacks still score decisions


def test_observation_privacy_no_opponent_hands_or_stock_order():
    recorders = []
    bots = []
    for index in range(3):
        inner = rummy_baselines.make_rummy_baselines(1, seed=43 + index)[0]
        inner.name = f"Base{index}"
        recorder = Recording(inner)
        recorders.append(recorder)
        bots.append(recorder)
    result = play_rummy_match(bots, seed=43)
    assert result["faults"] == [0, 0, 0]
    schema = {
        "protocol", "game", "rules_version", "seat", "players", "hand",
        "wild_rank", "stock_remaining", "discard_top", "discard_size",
        "turn", "history", "decision_number", "decision_cap",
    }
    for recorder in recorders:
        for observation in recorder.seen:
            assert set(observation) == schema
            assert observation["protocol"] == PROTOCOL
            assert observation["rules_version"] == RULES_VERSION
            assert observation["game"] == GAME_ID
            assert len(observation["hand"]) in (HAND_SIZE, HAND_SIZE + 1)
            for player in observation["players"]:
                assert set(player) == {"seat", "name", "count"}
            for event in observation["history"]:
                # stock draws never name their card; discard draws name only
                # the public top card that was already visible to everyone
                if event["type"] == "draw":
                    if event["from"] == "stock":
                        assert event["card"] is None
                    else:
                        assert isinstance(event["card"], str)
                assert event["type"] != "declaration"  # terminal, never observed
            # no opponent hand, stock order, or deep discard ever appears
            encoded = json.dumps(observation)
            assert '"XJ1"' not in encoded or any(
                card in observation["hand"] for card in ("XJ1", "XJ2")
            ) or "wrong_declaration" in encoded


def test_baselines_complete_legal_matches_with_a_winner():
    for seats in SEATS:
        result = play_rummy_match(
            rummy_baselines.make_rummy_baselines(seats, seed=seats), seed=100 + seats,
        )
        assert result["terminal_reason"] in ("win", "cap")
        assert result["winner_seats"]
        assert result["faults"] == [0] * seats
        assert result["errors"] == [None] * seats
        share = 1.0 / len(result["winner_seats"])
        assert result["points"] == [
            share if i in result["winner_seats"] else 0.0 for i in range(seats)
        ]
        end = end_log(result)
        total = sum(len(hand) for hand in end["hands"]) + len(end["stock"]) + len(end["discard"])
        assert total == 106
        assert result["decisions"] <= DECISION_CAP + 3  # the current turn finishes


def test_baseline_factory_bounds_and_unique_names():
    assert rummy_baselines.make_rummy_baselines(0) == []
    table = rummy_baselines.make_rummy_baselines(6, seed=1)
    assert len(table) == 6
    assert len({bot.name for bot in table}) == 6
    with pytest.raises(ValueError):
        rummy_baselines.make_rummy_baselines(7)
    with pytest.raises(ValueError):
        rummy_baselines.make_rummy_baselines(-1)


def test_baselines_are_deterministic_per_instance_seed():
    seen = set()
    for baseline_seed, match_seed in ((50, 51), (51, 51), (50, 52), (51, 52), (50, 53)):
        result = play_rummy_match(
            rummy_baselines.make_rummy_baselines(4, seed=baseline_seed), seed=match_seed,
        )
        outcome = (tuple(result["points"]), result["decisions"], tuple(result["faults"]))
        again = play_rummy_match(
            rummy_baselines.make_rummy_baselines(4, seed=baseline_seed), seed=match_seed,
        )
        assert outcome == (
            tuple(again["points"]), again["decisions"], tuple(again["faults"]),
        )  # same instance seeds replay identically
        seen.add(outcome)
    assert len(seen) > 1, "different baseline seeds must steer play somewhere"
