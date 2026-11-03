"""Stack Theory UNO v1 engine rules, determinism, privacy, and fallbacks."""
import pytest

from arena.games.common.deck import Deck
from arena.games.uno import baselines as uno_baselines
from arena.games.uno.engine import (
    COLORS,
    DECISION_CAP,
    HAND_SIZE,
    card_color,
    card_face,
    is_wild,
    matches,
    play_uno_match,
    sort_key,
    uno_deck,
)
from arena.sandbox import SandboxDown

OBSERVATION_KEYS = {
    "protocol", "game", "rules_version", "seat", "players", "hand",
    "discard_top", "active_color", "direction", "active_seat", "pending_draw",
    "turn", "decision_number", "decision_cap",
}


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


def end_log(result):
    return next(entry for entry in result["log"] if entry["type"] == "end")


def is_playable(card, observation):
    return matches(card, observation["discard_top"], observation["active_color"])


def dominant_color(hand):
    return max("rygb", key=lambda color: sum(1 for card in hand if card[0] == color))


def legal_action(observation):
    """A complete legal policy: shed non-wilds first, wilds with a real color."""
    turn = observation["turn"]
    kind = turn["type"]
    if kind == "penalty":
        return {"type": "draw"}
    if kind == "uno":
        return {"type": "uno"}
    if kind == "challenge":
        return {"type": "pass"}
    if kind == "post_draw":
        card = turn["card"]
        if card[0] == "w":
            return {"type": "play", "card": card, "color": dominant_color(observation["hand"])}
        return {"type": "play", "card": card}
    legal = [card for card in observation["hand"] if is_playable(card, observation)]
    naturals = [card for card in legal if card[0] != "w"]
    if naturals:
        return {"type": "play", "card": min(naturals, key=sort_key)}
    if legal:
        return {"type": "play", "card": legal[0], "color": dominant_color(observation["hand"])}
    return {"type": "draw"}


def draw_only(observation):
    """A legal bot that never plays: draws when it must, passes everything else."""
    kind = observation["turn"]["type"]
    if kind in ("play", "penalty"):
        return {"type": "draw"}
    if kind == "post_draw":
        return {"type": "pass"}
    if kind == "uno":
        return {"type": "uno"}
    return {"type": "pass"}  # challenge window


def setup_for(seed, seats):
    """Mirror the engine's private deal + start-card flip for a fixed seed."""
    deck = Deck(uno_deck(), seed)
    deck.shuffle()
    dealt = deck.draw(HAND_SIZE * seats)
    hands = [sorted(dealt[seat::seats], key=sort_key) for seat in range(seats)]
    while True:
        card = deck.draw(1)[0]
        if is_wild(card):
            continue
        return hands, card, deck


def flip_card_for(seed, seats):
    """The card the engine would flip first, before any wild re-flip."""
    deck = Deck(uno_deck(), seed)
    deck.shuffle()
    deck.draw(HAND_SIZE * seats)
    return deck.draw(1)[0]


def wdf_first(observation):
    """Plays a held wild draw four on the seat's first turn, color green."""
    if observation["turn"]["type"] == "play":
        for card in observation["hand"]:
            if card_face(card) == "wild4":
                return {"type": "play", "card": card, "color": "g"}
    return legal_action(observation)


def find_seed(seats, predicate, limit=4000):
    """First seed whose mirrored setup satisfies the predicate."""
    for seed in range(limit):
        hands, start, deck = setup_for(seed, seats)
        nxt = deck.draw(1)[0]
        if predicate(hands, start, nxt):
            return seed
    raise AssertionError("no seed satisfied the predicate")


def conservation(result):
    end = end_log(result)
    total = sum(len(hand) for hand in end["hands"])
    return total + len(end["discard"]) + end["draw_remaining"]


def plays(result):
    return [entry for entry in result["log"] if entry["type"] == "play"]


def draws(result):
    return [entry for entry in result["log"] if entry["type"] == "draw"]


def test_deck_composition_and_unique_ids():
    deck = uno_deck()
    assert len(deck) == 108 and len(set(deck)) == 108
    for color in COLORS:
        assert sum(1 for card in deck if card_color(card) == color) == 25
        assert f"{color}0a" in deck
        for face in ("skip", "reverse", "draw2"):
            copies = [card for card in deck
                      if card_color(card) == color and card_face(card) == face]
            assert len(copies) == 2
    assert sum(1 for card in deck if card.startswith("wwild4")) == 4
    assert sum(1 for card in deck
               if card.startswith("wwild") and not card.startswith("wwild4")) == 4
    # ID parsing is uniform: color / face / copy.
    assert card_color("wwild4d") == "w" and card_face("wwild4d") == "wild4"
    assert card_face("bskipb") == "skip" and is_wild("gdraw2b") is False


def test_deterministic_replay_from_seed_and_bots():
    first = play_uno_match(uno_baselines.make_uno_baselines(4, seed=99), seed=123, capture=True)
    second = play_uno_match(uno_baselines.make_uno_baselines(4, seed=99), seed=123, capture=True)
    assert first["points"] == second["points"]
    assert first["decisions"] == second["decisions"]
    assert first["log"] == second["log"]
    assert first["frames"] == second["frames"]
    # The versioned replay wrapper and the exact result key set.
    assert set(first["frames"]) == {"game", "protocol", "names", "frames"}
    assert first["frames"]["game"] == "uno" and first["frames"]["protocol"] == 1
    assert set(first) == {
        "points", "winner_seats", "terminal_reason", "faults", "errors", "hands",
        "matches", "decisions", "final_action", "names", "log", "frames",
    }


def test_108_card_conservation_and_no_duplicates():
    for seed in (3, 77, 2024):
        bots = uno_baselines.make_uno_baselines(3, seed=seed)
        result = play_uno_match(bots, seed=seed)
        assert conservation(result) == 108
        end = end_log(result)
        seen = [card for hand in end["hands"] for card in hand] + end["discard"]
        assert len(seen) == len(set(seen))


def test_start_card_is_never_wild_and_uses_the_bottom_reflip():
    for seed in range(60):
        bots = uno_baselines.make_uno_baselines(4, seed=seed)
        result = play_uno_match(bots, seed=seed)
        start = next(entry for entry in result["log"] if entry["type"] == "start")
        assert not is_wild(start["card"])
    seed = next(s for s in range(300) if is_wild(flip_card_for(s, 4)))
    result = play_uno_match(uno_baselines.make_uno_baselines(4, seed=seed), seed=seed)
    start = next(entry for entry in result["log"] if entry["type"] == "start")
    assert start["reflipped"] >= 1 and not is_wild(start["card"])


def test_illegal_play_faults_and_falls_back_to_draw():
    seed = find_seed(4, lambda hands, start, nxt: any(
        not matches(card, start, card_color(start)) for card in hands[0]))
    state = {"done": False}

    def one_bad_play(observation):
        if observation["turn"]["type"] == "play" and observation["seat"] == 0 and not state["done"]:
            bad = next(card for card in observation["hand"]
                       if not is_playable(card, observation))
            state["done"] = True
            return {"type": "play", "card": bad}  # owned but not matching
        return legal_action(observation)

    bots = [Scripted("B0", one_bad_play), *uno_baselines.make_uno_baselines(3, seed=41)]
    result = play_uno_match(bots, seed=seed)
    assert result["faults"][0] >= 1
    assert result["errors"][0] == "invalid play action"
    assert conservation(result) == 108
    # The fallback for an invalid play is drawing one card.
    fallback = next(entry for entry in draws(result)
                    if entry["seat"] == 0 and entry["fault"])
    assert fallback["reason"] == "turn" and fallback["count"] == 1


def test_unowned_card_faults():
    state = {"done": False}

    def junk_once(observation):
        if observation["turn"]["type"] == "play" and not state["done"]:
            state["done"] = True
            return {"type": "play", "card": "zz9x"}
        return legal_action(observation)

    bots = [Scripted("J", junk_once), *uno_baselines.make_uno_baselines(3, seed=42)]
    result = play_uno_match(bots, seed=42)
    assert result["faults"][0] >= 1
    assert result["errors"][0] == "invalid play action"


def test_wild_requires_a_color_field():
    seed = find_seed(4, lambda hands, start, nxt: any(is_wild(card) for card in hands[1]))
    state = {"done": False}

    def wild_without_color(observation):
        if observation["turn"]["type"] == "play" and not state["done"]:
            wild = next(card for card in observation["hand"] if is_wild(card))
            state["done"] = True
            return {"type": "play", "card": wild}  # no color
        return legal_action(observation)

    bots = [Scripted("D0", draw_only), Scripted("W1", wild_without_color),
            Scripted("D2", draw_only), Scripted("D3", draw_only)]
    result = play_uno_match(bots, seed=seed)
    assert result["faults"][1] >= 1
    assert result["errors"][1] == "invalid play action"


def test_wild_color_choice_is_public():
    seed = find_seed(4, lambda hands, start, nxt:
                     card_face(start).isdigit()
                     and any(card_face(card) == "wild" for card in hands[1]))
    recorders = [Recording(Scripted("D0", draw_only)),
                 Recording(Scripted("W1", legal_action)),
                 Recording(Scripted("D2", draw_only)),
                 Recording(Scripted("D3", draw_only))]
    result = play_uno_match(recorders, seed=seed, capture=True)
    wild_plays = [entry for entry in plays(result) if is_wild(entry["card"])]
    assert wild_plays, "seat 1 holds a wild and must have played it"
    wild_card = wild_plays[0]["card"]
    chosen = wild_plays[0]["color"]
    assert chosen in COLORS
    # The play frame carries the chosen color; every later observation shows it.
    play_frames = [f for f in result["frames"]["frames"]
                   if f["kind"] == "play" and f["card"] == wild_card]
    assert play_frames[0]["color"] == chosen
    for recorder in recorders:
        for observation in recorder.seen:
            if observation["discard_top"] == wild_card:
                assert observation["active_color"] == chosen


def test_skip_advances_two():
    seed = find_seed(4, lambda hands, start, nxt:
                     card_face(start).isdigit()
                     and any(card_color(card) == card_color(start)
                             and card_face(card) == "skip" for card in hands[1]))

    def skip_first(observation):
        if observation["turn"]["type"] == "play":
            for card in observation["hand"]:
                if card_face(card) == "skip" and is_playable(card, observation):
                    return {"type": "play", "card": card}
        return legal_action(observation)

    bots = [Scripted("D0", draw_only), Scripted("S1", skip_first),
            Scripted("D2", draw_only), Scripted("D3", draw_only)]
    result = play_uno_match(bots, seed=seed, capture=True)
    first_skip = next(entry for entry in plays(result) if card_face(entry["card"]) == "skip")
    index = result["log"].index(first_skip)
    after = result["log"][index + 1]
    assert after["type"] == "draw" and after["seat"] == 3  # seat 2 was skipped
    assert any(frame["kind"] == "skip" for frame in result["frames"]["frames"])


def test_reverse_flips_direction():
    seed = find_seed(4, lambda hands, start, nxt:
                     card_face(start).isdigit()
                     and any(card_color(card) == card_color(start)
                             and card_face(card) == "reverse" for card in hands[1]))

    def reverse_first(observation):
        if observation["turn"]["type"] == "play":
            for card in observation["hand"]:
                if card_face(card) == "reverse" and is_playable(card, observation):
                    return {"type": "play", "card": card}
        return legal_action(observation)

    bots = [Scripted("D0", draw_only), Scripted("R1", reverse_first),
            Scripted("D2", draw_only), Scripted("D3", draw_only)]
    result = play_uno_match(bots, seed=seed, capture=True)
    first_reverse = next(entry for entry in plays(result)
                         if card_face(entry["card"]) == "reverse")
    index = result["log"].index(first_reverse)
    after = result["log"][index + 1]
    assert after["type"] == "draw" and after["seat"] == 0  # direction flipped to ccw
    reversal = next(frame for frame in result["frames"]["frames"]
                    if frame["kind"] == "reverse")
    assert reversal["direction"] == "ccw"


def test_two_player_reverse_acts_as_skip():
    seed = find_seed(2, lambda hands, start, nxt:
                     card_face(start).isdigit()
                     and any(card_color(card) == card_color(start)
                             and card_face(card) == "reverse" for card in hands[1]))
    bots = [Scripted("D0", draw_only), Scripted("R1", legal_action)]
    result = play_uno_match(bots, seed=seed, capture=True)
    first_reverse = next(entry for entry in plays(result)
                         if card_face(entry["card"]) == "reverse")
    index = result["log"].index(first_reverse)
    after = result["log"][index + 1]
    # The same player plays again; the frame renders it as a skip.
    assert after["seat"] == 1
    reversal = next(frame for frame in result["frames"]["frames"]
                    if frame["kind"] == "skip")
    assert reversal["seat"] == 0


def test_draw_two_forces_a_penalty_turn():
    seed = find_seed(4, lambda hands, start, nxt:
                     card_face(start).isdigit()
                     and any(card_color(card) == card_color(start)
                             and card_face(card) == "draw2" for card in hands[1]))
    bots = [Scripted("D0", draw_only), Scripted("A1", legal_action),
            Scripted("D2", draw_only), Scripted("D3", draw_only)]
    result = play_uno_match(bots, seed=seed, capture=True)
    first_draw2 = next(entry for entry in plays(result)
                       if card_face(entry["card"]) == "draw2")
    index = result["log"].index(first_draw2)
    penalty = result["log"][index + 1]
    assert penalty["type"] == "draw" and penalty["seat"] == 2
    assert penalty["reason"] == "penalty" and penalty["count"] == 2
    after = result["log"][index + 2]
    assert after["type"] == "draw" and after["seat"] == 3  # seat 2 was skipped
    frames = result["frames"]["frames"]
    served = next(frame for frame in frames if frame["kind"] == "penalty")
    assert served["seat"] == 2 and served["count"] == 2


def test_wild_draw_four_challenge_window_pass():
    seed = find_seed(4, lambda hands, start, nxt:
                     card_face(start).isdigit()
                     and any(card_face(card) == "wild4" for card in hands[1]))
    bots = [Scripted("D0", draw_only), Scripted("W1", wdf_first),
            Scripted("C2", draw_only), Scripted("D3", draw_only)]
    result = play_uno_match(bots, seed=seed, capture=True)
    first_wdf = next(entry for entry in plays(result)
                     if card_face(entry["card"]) == "wild4")
    index = result["log"].index(first_wdf)
    challenge = result["log"][index + 1]
    assert challenge["type"] == "pass" and challenge["seat"] == 2
    served = result["log"][index + 2]
    assert served["type"] == "draw" and served["seat"] == 2
    assert served["reason"] == "penalty" and served["count"] == 4
    after = result["log"][index + 3]
    assert after["type"] == "draw" and after["seat"] == 3  # challenger skipped
    frames = result["frames"]["frames"]
    assert next(frame["count"] for frame in frames if frame["kind"] == "penalty") == 4


def test_wild_draw_four_successful_challenge():
    seed = find_seed(4, lambda hands, start, nxt:
                     card_face(start).isdigit()
                     and any(card_face(card) == "wild4" for card in hands[1])
                     and any(card_color(card) == card_color(start) for card in hands[1]))
    state = {"challenged": False}

    def challenger(observation):
        if observation["turn"]["type"] == "challenge" and not state["challenged"]:
            state["challenged"] = True
            return {"type": "challenge"}
        return draw_only(observation)

    bots = [Scripted("D0", draw_only), Scripted("W1", wdf_first),
            Scripted("C2", challenger), Scripted("D3", draw_only)]
    result = play_uno_match(bots, seed=seed)
    outcome = next(entry for entry in result["log"]
                   if entry["type"] == "challenge_result")
    assert outcome["guilty"] is True and outcome["player"] == 1
    index = result["log"].index(outcome)
    served = result["log"][index + 1]
    # The guilty wild-four player draws the four cards.
    assert served["type"] == "draw" and served["seat"] == 1
    assert served["reason"] == "challenge" and served["count"] == 4
    after = result["log"][index + 2]
    # The challenger takes their normal turn (no penalty, not skipped).
    assert after["seat"] == 2 and after["reason"] == "turn"


def test_wild_draw_four_failed_challenge_costs_six():
    seed = find_seed(4, lambda hands, start, nxt:
                     card_face(start).isdigit()
                     and any(card_face(card) == "wild4" for card in hands[1])
                     and not any(card_color(card) == card_color(start)
                                 for card in hands[1]))
    def challenger(observation):
        if observation["turn"]["type"] == "challenge":
            return {"type": "challenge"}
        return draw_only(observation)

    bots = [Scripted("D0", draw_only), Scripted("W1", wdf_first),
            Scripted("C2", challenger), Scripted("D3", draw_only)]
    result = play_uno_match(bots, seed=seed)
    outcome = next(entry for entry in result["log"]
                   if entry["type"] == "challenge_result")
    assert outcome["guilty"] is False
    index = result["log"].index(outcome)
    served = result["log"][index + 1]
    # The failed challenger draws the four plus two more, and is skipped.
    assert served["type"] == "draw" and served["seat"] == 2
    assert served["reason"] == "penalty" and served["count"] == 6
    after = result["log"][index + 2]
    assert after["seat"] == 3


def test_draw_one_may_play_only_the_drawn_card():
    seed = find_seed(4, lambda hands, start, nxt:
                     card_face(start).isdigit() and matches(nxt, start, card_color(start)))
    recorders = [Recording(Scripted("R0", draw_only)),
                 Recording(Scripted("P1", draw_only)),
                 Recording(Scripted("D2", draw_only)),
                 Recording(Scripted("D3", draw_only))]

    def draw_then_play(observation):
        if observation["turn"]["type"] == "post_draw":
            card = observation["turn"]["card"]
            if card[0] == "w":
                return {"type": "play", "card": card, "color": "g"}
            return {"type": "play", "card": card}
        return draw_only(observation)

    recorders[1] = Recording(Scripted("P1", draw_then_play))
    result = play_uno_match(recorders, seed=seed)
    first_draw = next(entry for entry in draws(result)
                      if entry["seat"] == 1 and entry["reason"] == "turn")
    index = result["log"].index(first_draw)
    drawn_card = first_draw["cards"][0]
    follow_up = result["log"][index + 1]
    # The drawn card was playable and was played through immediately.
    assert follow_up["type"] == "play" and follow_up["seat"] == 1
    assert follow_up["card"] == drawn_card
    assert result["faults"][1] == 0


def test_post_draw_rejects_any_other_card():
    seed = find_seed(4, lambda hands, start, nxt:
                     card_face(start).isdigit() and matches(nxt, start, card_color(start))
                     and len(hands[1]) >= 2)
    state = {"done": False}

    def play_wrong_card(observation):
        if observation["turn"]["type"] == "post_draw" and not state["done"]:
            others = [card for card in observation["hand"]
                      if card != observation["turn"]["card"]]
            state["done"] = True
            return {"type": "play", "card": others[0]}
        return legal_action(observation)

    bots = [Scripted("D0", draw_only), Scripted("B1", play_wrong_card),
            Scripted("D2", draw_only), Scripted("D3", draw_only)]
    result = play_uno_match(bots, seed=seed)
    assert result["faults"][1] >= 1
    assert result["errors"][1] == "invalid post-draw action"


def test_uno_decline_costs_two_cards_once():
    seed = find_seed(2, lambda hands, start, nxt: card_face(start).isdigit())
    state = {"declined": False}

    def shed_and_decline_once(observation):
        if observation["turn"]["type"] == "uno" and not state["declined"]:
            state["declined"] = True
            return {"type": "pass"}
        return legal_action(observation)

    bots = [Scripted("S0", shed_and_decline_once), Scripted("D1", draw_only)]
    result = play_uno_match(bots, seed=seed)
    catches = [entry for entry in result["log"] if entry["type"] == "uno_penalty"]
    assert len(catches) == 1 and catches[0]["seat"] == 0 and catches[0]["count"] == 2
    assert result["terminal_reason"] == "win" and result["winner_seats"] == [0]
    # Any later down-to-one play declares properly instead.
    assert any(entry["type"] == "uno" for entry in result["log"])
    assert conservation(result) == 108


def test_uno_declaration_is_public():
    seed = find_seed(2, lambda hands, start, nxt: card_face(start).isdigit())
    recorder = Recording(Scripted("D1", draw_only))
    bots = [Scripted("S0", legal_action), recorder]
    result = play_uno_match(bots, seed=seed, capture=True)
    declarations = [entry for entry in result["log"] if entry["type"] == "uno"]
    assert declarations and all(entry["seat"] == 0 for entry in declarations)
    assert any(frame["kind"] == "uno" for frame in result["frames"]["frames"])
    # The uno flag is public while seat 0 still holds exactly one card.
    assert any(observation["players"][0]["uno"] is True for observation in recorder.seen)
    assert result["winner_seats"] == [0]


def test_draw_only_table_hits_the_cap_and_shares():
    bots = [Scripted(f"Draw{i}", draw_only) for i in range(4)]
    result = play_uno_match(bots, seed=77, decision_cap=40)
    assert result["terminal_reason"] == "cap"
    end = end_log(result)
    fewest = min(len(hand) for hand in end["hands"])
    winners = [i for i in range(4) if len(end["hands"][i]) == fewest]
    assert result["winner_seats"] == winners
    share = 1.0 / len(winners)
    assert result["points"] == [share if i in winners else 0.0 for i in range(4)]


def test_decision_cap_fewest_cards_wins_and_ties_share():
    bots = uno_baselines.make_uno_baselines(4, seed=13)
    result = play_uno_match(bots, seed=13, decision_cap=8)
    assert result["terminal_reason"] == "cap"
    end = end_log(result)
    fewest = min(len(hand) for hand in end["hands"])
    winners = [i for i in range(4) if len(end["hands"][i]) == fewest]
    assert result["winner_seats"] == winners
    share = 1.0 / len(winners)
    assert result["points"] == [share if i in winners else 0.0 for i in range(4)]


def test_deck_exhaustion_reshuffles_and_stays_conserved():
    # A shedder that always declines UNO never wins and keeps drawing its
    # 2-card catch penalties, so the draw stack drains while the discard grows.
    def declining_shedder(observation):
        if observation["turn"]["type"] == "uno":
            return {"type": "pass"}
        return legal_action(observation)

    result = play_uno_match(
        [Scripted("S0", declining_shedder), Scripted("D1", draw_only)],
        seed=5, capture=True)
    reshuffles = [entry for entry in result["log"] if entry["type"] == "reshuffle"]
    assert reshuffles, "the draining match must exhaust and reshuffle the stack"
    assert any(frame["kind"] == "reshuffle" for frame in result["frames"]["frames"])
    assert conservation(result) == 108


def test_last_card_wild_draw_four_is_judged_before_the_win():
    seed = find_seed(2, lambda hands, start, nxt:
                     any(card_face(card) == "wild4" for card in hands[1]))

    def finisher(observation):
        turn = observation["turn"]
        if turn["type"] == "play":
            hand = observation["hand"]
            legal = [card for card in hand if is_playable(card, observation)]
            plain = [card for card in legal if not is_wild(card)]
            if plain:
                return {"type": "play", "card": min(plain, key=sort_key)}
            if len(hand) == 1 and is_wild(hand[0]):
                return {"type": "play", "card": hand[0], "color": "g"}
            wilds = [card for card in legal if is_wild(card) and card_face(card) != "wild4"]
            if wilds:
                return {"type": "play", "card": wilds[0], "color": dominant_color(hand)}
            return {"type": "draw"}
        if turn["type"] == "post_draw":
            card = turn["card"]
            if card_face(card) != "wild4":
                return {"type": "play", "card": card}
            return {"type": "pass"}  # hoard the four for the final play
        if turn["type"] == "penalty":
            return {"type": "draw"}
        if turn["type"] == "uno":
            return {"type": "uno"}
        return {"type": "pass"}

    def challenger(observation):
        if observation["turn"]["type"] == "challenge":
            return {"type": "challenge"}
        return draw_only(observation)

    # Passing the window: the finisher wins with the wild four.
    bots = [Scripted("D0", draw_only), Scripted("F1", finisher)]
    result = play_uno_match(bots, seed=seed)
    assert result["terminal_reason"] == "win" and result["winner_seats"] == [1]
    last_play = plays(result)[-1]
    assert card_face(last_play["card"]) == "wild4"

    # Challenging the window: an empty hand is always innocent, still a win.
    bots = [Scripted("C0", challenger), Scripted("F1", finisher)]
    result = play_uno_match(bots, seed=seed)
    outcome = next(entry for entry in result["log"]
                   if entry["type"] == "challenge_result")
    assert outcome["guilty"] is False
    assert result["terminal_reason"] == "win" and result["winner_seats"] == [1]


def test_garbage_bot_faults_do_not_break_the_match():
    class Garbage:
        name = "Garbage"

        def reset(self):
            pass

        def act(self, observation):
            kind = observation["turn"]["type"]
            if kind == "play":
                return {"type": "play", "card": "zz9x"}
            if kind == "post_draw":
                return {"type": "play", "card": "not-mine"}
            if kind == "penalty":
                return {"type": "pass"}  # wrong action type on purpose
            if kind == "uno":
                return {"type": "explode"}
            return {"type": 42}

    result = play_uno_match([Garbage(), *uno_baselines.make_uno_baselines(3, seed=5)], seed=5)
    assert result["faults"][0] >= 1
    assert result["errors"][0] is not None
    assert result["terminal_reason"] == "win" and len(result["winner_seats"]) == 1
    assert conservation(result) == 108


def test_sandbox_down_is_infrastructure_and_propagates():
    class Down:
        name = "Down"

        def reset(self):
            pass

        def act(self, observation):
            raise SandboxDown("daemon is down")

    class DownOnReset(Down):
        def reset(self):
            raise SandboxDown("unavailable")

    with pytest.raises(SandboxDown):
        play_uno_match([Down(), *uno_baselines.make_uno_baselines(3, seed=6)], seed=6)
    with pytest.raises(SandboxDown):
        play_uno_match([DownOnReset(), *uno_baselines.make_uno_baselines(3, seed=6)], seed=6)


def test_observations_never_leak_hidden_state():
    recorders = []
    for index in range(4):
        inner = uno_baselines.make_uno_baselines(1, seed=21)[0]
        inner.name = f"Base{index}"
        recorder = Recording(inner)
        recorders.append(recorder)
    play_uno_match(recorders, seed=21, capture=True)
    for recorder in recorders:
        for observation in recorder.seen:
            # The frozen visibility table is exhaustive: exactly these keys.
            assert set(observation) == OBSERVATION_KEYS
            assert observation["game"] == "uno" and observation["protocol"] == 1
            assert observation["active_color"] in COLORS
            assert observation["direction"] in ("cw", "ccw")
            assert observation["pending_draw"] >= 0
            for player in observation["players"]:
                assert set(player) == {"seat", "name", "count", "uno"}
    # Public frames never contain hands, drawn cards, deck order, or the seed.
    result = play_uno_match(recorders, seed=22, capture=True)
    for frame in result["frames"]["frames"]:
        assert not ({"hand", "cards", "seed", "deck", "drawn"} & set(frame))
        if "card" in frame:
            assert frame["kind"] in ("start", "play")


def test_baselines_complete_legal_matches_with_one_winner():
    for seats in (2, 3, 4):
        for seed in (31, 32, 33):
            bots = uno_baselines.make_uno_baselines(seats, seed=seed)
            result = play_uno_match(bots, seed=seed)
            assert result["terminal_reason"] == "win"
            assert len(result["winner_seats"]) == 1
            assert result["faults"] == [0] * seats
            assert result["decisions"] < DECISION_CAP
            winner = result["winner_seats"][0]
            assert len(end_log(result)["hands"][winner]) == 0
            assert conservation(result) == 108


def test_baseline_factory_and_match_validation():
    assert uno_baselines.make_uno_baselines(0) == []
    with pytest.raises(ValueError):
        uno_baselines.make_uno_baselines(5)
    with pytest.raises(ValueError):
        play_uno_match([], seed=1)
    with pytest.raises(ValueError):
        play_uno_match(uno_baselines.make_uno_baselines(2) + uno_baselines.make_uno_baselines(3, seed=2), seed=1)
    with pytest.raises(ValueError):
        play_uno_match(uno_baselines.make_uno_baselines(2), seed=1, decision_cap=0)
    with pytest.raises(ValueError):
        play_uno_match(uno_baselines.make_uno_baselines(2), seed=1, decision_cap=100_001)
