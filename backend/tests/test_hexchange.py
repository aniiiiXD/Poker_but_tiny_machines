"""Stack Theory Hexchange v1 engine rules, trade overlay, privacy, and fallbacks."""
import random

import pytest

from arena.games.hexchange import baselines as hex_baselines
from arena.games.hexchange import engine as hex_engine
from arena.games.hexchange.board import (
    COSTS,
    NUMBER_TOKENS,
    RESOURCE_TYPES,
    build_board,
    hand_total,
)
from arena.games.hexchange.engine import DEV_TYPES, play_hexchange_match
from arena.sandbox import SandboxDown

DEV_TOTAL = 25
SETTLEMENT_COST = COSTS["settlement"]
RESOURCES = RESOURCE_TYPES


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


class Garbage:
    """Returns nonsense for every decision; exercises every fault fallback."""

    name = "Garbage"

    def reset(self):
        pass

    def act(self, observation):
        return {"type": "explode"}


class Down:
    """Infrastructure failure in a bot's own clothing."""

    name = "Down"

    def reset(self):
        pass

    def act(self, observation):
        raise SandboxDown("daemon is down")


# -- observation-side legality mirrors (independent of the engine) -------------


def distance_spots(observation):
    buildings = {b["vertex"] for b in observation["buildings"]}
    return [
        v["id"] for v in observation["board"]["vertices"]
        if v["id"] not in buildings
        and all(u not in buildings for u in v["vertices"])
    ]


def connected_spots(observation, seat):
    roads = {r["edge"]: r["seat"] for r in observation["roads"]}
    return [
        v for v in distance_spots(observation)
        if any(roads.get(e) == seat
               for e in observation["board"]["vertices"][v]["edges"])
    ]


def road_edges(observation, seat):
    roads = {r["edge"]: r["seat"] for r in observation["roads"]}
    buildings = {b["vertex"]: (b["seat"], b["kind"]) for b in observation["buildings"]}

    def connects(vertex):
        occupant = buildings.get(vertex)
        if occupant is not None:
            return occupant[0] == seat
        return any(roads.get(e) == seat
                   for e in observation["board"]["vertices"][vertex]["edges"])

    return [
        e["id"] for e in observation["board"]["edges"]
        if e["id"] not in roads
        and (connects(e["vertices"][0]) or connects(e["vertices"][1]))
    ]


def setup_road_edge(observation, seat):
    vertex = None
    for event in observation["history"]:
        if (event.get("type") == "build" and event.get("built") == "settlement"
                and event.get("seat") == seat):
            vertex = event["id"]
    roads = {r["edge"] for r in observation["roads"]}
    return min(e for e in observation["board"]["vertices"][vertex]["edges"]
               if e not in roads)


def steal_targets(observation, seat, hex_id):
    buildings = {b["vertex"]: (b["seat"], b["kind"]) for b in observation["buildings"]}
    counts = {p["seat"]: p["count"] for p in observation["players"]}
    targets = set()
    for vertex in observation["board"]["hexes"][hex_id]["vertices"]:
        occupant = buildings.get(vertex)
        if (occupant is not None and occupant[0] != seat
                and counts[occupant[0]] > 7):
            targets.add(occupant[0])
    return sorted(targets)


def adjacent_to_hex(observation, seat, hex_id):
    buildings = {b["vertex"]: (b["seat"], b["kind"]) for b in observation["buildings"]}
    return any(
        occupant is not None and occupant[0] == seat
        for vertex in observation["board"]["hexes"][hex_id]["vertices"]
        for occupant in [buildings.get(vertex)]
    )


# -- scripted behaviors ---------------------------------------------------------


def valid_player(fn):
    """Setup/robber/free_road answered legally; respond and main come from `fn`."""
    def behavior(observation):
        turn = observation["turn"]
        seat = observation["seat"]
        kind = turn["type"]
        if kind == "setup_settlement":
            return {"type": "build_settlement", "vertex": distance_spots(observation)[0]}
        if kind == "setup_road":
            return {"type": "build_road", "edge": setup_road_edge(observation, seat)}
        if kind == "robber":
            hex_id = next(h for h in range(len(observation["board"]["hexes"]))
                          if h != observation["robber"])
            targets = steal_targets(observation, seat, hex_id)
            return {"type": "move_robber", "hex": hex_id,
                    "steal": targets[0] if targets else None}
        if kind == "free_road":
            edges = road_edges(observation, seat)
            return {"type": "build_road", "edge": edges[0]}
        return fn(observation)
    return behavior


def end_turn_or_reject(observation):
    """A passive seat: ends its turns, rejects other seats' offers."""
    if observation["turn"]["type"] == "respond":
        return {"type": "reject"}
    return {"type": "end_turn"}


def offerer_behavior(memory):
    """Opens exactly one small offer per match: abundant for scarce."""
    def fn(observation):
        hand = observation["resources"]
        if memory.get("offered") or observation["turn"]["type"] != "main":
            return {"type": "end_turn"}
        give = max(RESOURCES, key=lambda r: (hand[r], -RESOURCES.index(r)))
        if hand[give] < 2:
            return {"type": "end_turn"}
        want = min([r for r in RESOURCES if r != give],
                   key=lambda r: (hand[r], RESOURCES.index(r)))
        memory["offered"] = True
        return {"type": "offer", "give": {give: 1}, "want": {want: 1}}
    return valid_player(fn)


def accepting_responder(observation):
    offer = observation["turn"]["offer"]
    if all(observation["resources"][r] >= c for r, c in offer["want"].items()):
        return {"type": "accept"}
    return {"type": "reject"}


def counter_responder(observation):
    hand = observation["resources"]
    give = max(RESOURCES, key=lambda r: (hand[r], -RESOURCES.index(r)))
    if hand[give] < 1:
        return {"type": "reject"}
    want = min([r for r in RESOURCES if r != give],
               key=lambda r: (hand[r], RESOURCES.index(r)))
    return {"type": "counter", "give": {give: 1}, "want": {want: 1}}


def run_until(predicate, make_bots, cap=500, seeds=60):
    for seed in range(seeds):
        result = play_hexchange_match(make_bots(seed), seed=seed,
                                      decision_cap=cap, capture=True)
        if predicate(result):
            return seed, result
    raise AssertionError("no seed in range satisfied the scenario precondition")


def log_of(result, kind):
    return [entry for entry in result["log"] if entry["type"] == kind]


def frames_of(result, kind):
    return [frame for frame in result["frames"] if frame["kind"] == kind]


def baseline_table(seats, seed):
    return hex_baselines.make_hexchange_table(seats, seed=seed)


# -- board generation -----------------------------------------------------------


def test_board_generation_is_legal_and_symmetric():
    for seed in (0, 7, 1234):
        board = build_board(random.Random(seed))
        assert len(board.hexes) == 19
        assert len(board.vertices) == 54
        assert len(board.edges) == 72
        terrains = [h["terrain"] for h in board.hexes]
        assert terrains.count("forest") == 4
        assert terrains.count("pasture") == 4
        assert terrains.count("wheat") == 4
        assert terrains.count("brick") == 3
        assert terrains.count("ore") == 3
        assert terrains.count("desert") == 1
        numbers = sorted(h["number"] for h in board.hexes if h["number"] is not None)
        assert numbers == sorted(NUMBER_TOKENS)
        assert all(h["number"] is None for h in board.hexes if h["terrain"] == "desert")
        assert board.desert_hex == next(h["id"] for h in board.hexes
                                        if h["terrain"] == "desert")
        for entry in board.hexes:
            assert len(set(entry["vertices"])) == 6
            assert len(set(entry["edges"])) == 6
            for neighbor in entry["neighbors"]:
                assert entry["id"] in board.hexes[neighbor]["neighbors"]
        for vertex in board.vertices:
            assert 1 <= len(vertex["hexes"]) <= 3
            for neighbor in vertex["vertices"]:
                assert vertex["id"] in board.vertices[neighbor]["vertices"]
            assert all(
                vertex["id"] in board.edges[edge]["vertices"]
                for edge in vertex["edges"]
            )
        for edge in board.edges:
            a, b = edge["vertices"]
            assert b in board.vertices[a]["vertices"]
            assert 1 <= len(edge["hexes"]) <= 2


def test_board_generation_is_deterministic_per_seed():
    for seed in (5, 99):
        first = build_board(random.Random(seed))
        second = build_board(random.Random(seed))
        assert [h["terrain"] for h in first.hexes] == [h["terrain"] for h in second.hexes]
        assert [h["number"] for h in first.hexes] == [h["number"] for h in second.hexes]
    a = build_board(random.Random(1))
    b = build_board(random.Random(2))
    assert [h["terrain"] for h in a.hexes] != [h["terrain"] for h in b.hexes] or \
        [h["number"] for h in a.hexes] != [h["number"] for h in b.hexes]


def test_production_dice_distribution_over_long_run():
    rolls = []
    for seed in (1, 2, 3):
        result = play_hexchange_match(baseline_table(4, seed), seed=seed,
                                      decision_cap=3000, capture=False)
        rolls.extend(entry["dice"][0] + entry["dice"][1] for entry in log_of(result, "roll"))
        for production in log_of(result, "production"):
            if not production.get("setup"):
                assert production["roll"] != 7  # a 7 never produces
    assert len(rolls) > 600
    histogram = {total: rolls.count(total) for total in range(2, 13)}
    assert all(count > 0 for count in histogram.values())
    assert histogram[7] > histogram[2]
    assert histogram[7] > histogram[12]
    assert histogram[7] > histogram[3]
    assert histogram[7] > histogram[11]


# -- setup ------------------------------------------------------------------------


def test_setup_snake_order_and_second_settlement_payout():
    seen = []

    def note(observation):
        turn = observation["turn"]
        seen.append((observation["seat"], turn["type"], turn.get("round")))
        return valid_player(end_turn_or_reject)(observation)

    bots = [Scripted(f"N{i}", note) for i in range(4)]
    result = play_hexchange_match(bots, seed=11, decision_cap=60, capture=True)
    setup_turns = [entry for entry in seen if entry[1].startswith("setup")]
    settlements = [entry for entry in setup_turns if entry[1] == "setup_settlement"]
    roads = [entry for entry in setup_turns if entry[1] == "setup_road"]
    assert [seat for seat, _, _ in settlements] == [0, 1, 2, 3, 3, 2, 1, 0]
    assert [seat for seat, _, _ in roads] == [0, 1, 2, 3, 3, 2, 1, 0]
    assert [round for _, _, round in settlements] == [1] * 4 + [2] * 4
    assert [round for _, _, round in roads] == [1] * 4 + [2] * 4
    assert [kind for _, kind, _ in setup_turns[::2]] == ["setup_settlement"] * 8
    # Every round-2 settlement pays one resource per adjacent non-desert hex.
    payouts = [entry for entry in log_of(result, "production") if entry.get("setup")]
    assert len(payouts) == 4
    board = build_board(random.Random(11))
    for payout in payouts:
        assert payout["gained"][payout["seat"]] >= 1
        settlements = [e for e in log_of(result, "build")
                       if e["built"] == "settlement" and e["seat"] == payout["seat"]]
        vertex = settlements[-1]["id"]
        expected = sum(1 for h in board.vertex_hexes(vertex)
                       if board.hexes[h]["terrain"] != "desert")
        assert payout["gained"][payout["seat"]] == expected


def test_setup_fallbacks_place_for_stalled_bots():
    bots = [Garbage(), Garbage(), Garbage(), Garbage()]
    result = play_hexchange_match(bots, seed=13, decision_cap=40, capture=True)
    builds = log_of(result, "build")
    first_roll = log_of(result, "roll")[0]
    setup_builds = [entry for entry in builds if entry["free"]]
    assert len(setup_builds) == 16  # 2 settlements + 2 roads for each of 4 seats
    for seat in range(4):
        mine = [entry for entry in setup_builds if entry["seat"] == seat]
        assert [entry["built"] for entry in mine] == ["settlement", "road",
                                                      "settlement", "road"]
    # All fallback placements happen during setup, before the first roll.
    log = result["log"]
    assert log.index(first_roll) > log.index(setup_builds[-1])


# -- placement legality and costs -------------------------------------------------


def test_distance_rule_enforced():
    def neighbor_build_attempt(observation):
        if observation["turn"]["type"] != "main":
            return {"type": "end_turn"}
        # Any vertex adjacent to an existing building violates the distance rule.
        buildings = {b["vertex"] for b in observation["buildings"]}
        board = observation["board"]["vertices"]
        for vertex in range(len(board)):
            if vertex not in buildings and any(
                    u in buildings for u in board[vertex]["vertices"]):
                return {"type": "build_settlement", "vertex": vertex}
        return {"type": "end_turn"}

    def make_bots(seed):
        return [
            Scripted("Rule", valid_player(neighbor_build_attempt)),
            Scripted("S1", valid_player(end_turn_or_reject)),
            Scripted("S2", valid_player(end_turn_or_reject)),
        ]

    _seed, result = run_until(lambda r: r["faults"][0] > 0, make_bots, cap=120)
    assert result["faults"][0] >= 1
    assert result["errors"][0] == "invalid main action"
    # The main-phase fallback is end_turn: no settlement was placed by the
    # illegal attempt (only the free setup placements exist).
    assert all(e["free"] for e in log_of(result, "build")
               if e["built"] == "settlement" and e["seat"] == 0)


def test_connectivity_and_cost_enforced():
    def unconnected_attempt(observation):
        if observation["turn"]["type"] != "main":
            return {"type": "end_turn"}
        connected = set(connected_spots(observation, observation["seat"]))
        targets = [v for v in distance_spots(observation) if v not in connected]
        if targets:
            return {"type": "build_settlement", "vertex": targets[-1]}
        return {"type": "end_turn"}

    def make_bots(seed):
        return [
            Scripted("Greedy", valid_player(unconnected_attempt)),
            Scripted("S1", valid_player(end_turn_or_reject)),
            Scripted("S2", valid_player(end_turn_or_reject)),
        ]

    _seed, result = run_until(lambda r: r["faults"][0] > 0, make_bots, cap=200)
    assert result["faults"][0] >= 1
    # Seat 0 never places a paid settlement: its picks are always unconnected,
    # and the fallback ends the turn without placing anything.
    assert all(e["free"] or e["seat"] != 0 for e in log_of(result, "build")
               if e["built"] == "settlement")


def test_build_costs_paid_exactly():
    deltas = {"settlement": -sum(SETTLEMENT_COST.values()), "road": -2, "city": -5}
    checked = set()
    for seed in (2, 4, 5):
        result = play_hexchange_match(baseline_table(4, seed), seed=seed,
                                      decision_cap=2000, capture=True)
        for previous, frame in zip(result["frames"], result["frames"][1:]):
            if frame["kind"] == "build" and not frame["free"]:
                seat = frame["seat"]
                delta = frame["counts"][seat] - previous["counts"][seat]
                assert delta == deltas[frame["built"]]
                checked.add(frame["built"])
            if frame["kind"] == "build" and frame["free"]:
                assert frame["counts"] == previous["counts"]
    assert {"settlement", "road"} <= checked  # cities are asserted in the sweep test


# -- bank and trade overlay ---------------------------------------------------------


def test_bank_trade_rules():
    def trader(observation):
        if observation["turn"]["type"] != "main":
            return {"type": "end_turn"}
        hand = observation["resources"]
        rich = [r for r in RESOURCES if hand[r] >= 4]
        if rich:
            give = max(rich, key=lambda r: (hand[r], -RESOURCES.index(r)))
            want = min([r for r in RESOURCES if r != give],
                       key=lambda r: (hand[r], RESOURCES.index(r)))
            return {"type": "bank_trade", "give": {give: 4}, "want": {want: 1}}
        return {"type": "end_turn"}

    def bad_trader(observation):
        if observation["turn"]["type"] != "main":
            return {"type": "end_turn"}
        hand = observation["resources"]
        rich = [r for r in RESOURCES if hand[r] >= 4]
        if rich:
            give = max(rich, key=lambda r: (hand[r], -RESOURCES.index(r)))
            # Wrong shapes: 3-for-1, same-type, and two-type gives.
            return {"type": "bank_trade", "give": {give: 3}, "want": {give: 1}}
        return {"type": "end_turn"}

    _seed, result = run_until(
        lambda r: any(f["kind"] == "bank_trade" for f in r["frames"]),
        lambda s: [Scripted("Trader", valid_player(trader)),
                   Scripted("S1", valid_player(end_turn_or_reject)),
                   Scripted("S2", valid_player(end_turn_or_reject))],
        cap=400,
    )
    for previous, frame in zip(result["frames"], result["frames"][1:]):
        if frame["kind"] == "bank_trade":
            seat = frame["seat"]
            assert frame["counts"][seat] - previous["counts"][seat] == -3  # -4 +1

    bots = [Scripted("Bad", valid_player(bad_trader)),
            Scripted("S1", valid_player(end_turn_or_reject)),
            Scripted("S2", valid_player(end_turn_or_reject))]
    _seed, result = run_until(
        lambda r: r["faults"][0] > 0,
        lambda s: bots, cap=400,
    )
    assert result["errors"][0] == "invalid main action"
    assert not any(f["kind"] == "bank_trade" and f["seat"] == 0 for f in result["frames"])


def test_trade_offer_then_accept_executes():
    def make_bots(seed):
        return [
            Scripted("Offerer", offerer_behavior({})),
            Scripted("Accepter", valid_player(accepting_responder)),
            Scripted("S2", valid_player(end_turn_or_reject)),
        ]

    _seed, result = run_until(
        lambda r: any(f["kind"] == "accept" and f["offered_by"] == 0 for f in r["frames"]),
        make_bots, cap=400,
    )
    accept = next(f for f in frames_of(result, "accept") if f["offered_by"] == 0)
    offer = next(f for f in frames_of(result, "offer") if f["seat"] == 0)
    assert accept["give"] == offer["give"] and accept["want"] == offer["want"]
    give_total = sum(offer["give"].values())
    want_total = sum(offer["want"].values())
    index = result["frames"].index(accept)
    before = result["frames"][index - 1]["counts"]
    assert accept["counts"][0] == before[0] + want_total - give_total
    assert accept["counts"][1] == before[1] + give_total - want_total
    assert accept["counts"][2] == before[2]
    assert sum(accept["counts"]) == sum(before)  # trades conserve total tokens
    log_accept = next(e for e in log_of(result, "accept") if e["offered_by"] == 0)
    assert sum(hand_total(hand) for hand in log_accept["hands_after"]) == sum(before)


def test_trade_reject_falls_through_to_next_seat():
    def make_bots(seed):
        return [
            Scripted("Offerer", offerer_behavior({})),
            Scripted("Refuser", valid_player(end_turn_or_reject)),
            Scripted("Accepter", valid_player(accepting_responder)),
        ]

    _seed, result = run_until(
        lambda r: any(f["kind"] == "accept" and f["seat"] == 2 for f in r["frames"]),
        make_bots, cap=400,
    )
    rejects = [f for f in frames_of(result, "reject") if f["seat"] == 1]
    accepts = [f for f in frames_of(result, "accept") if f["seat"] == 2]
    assert rejects and accepts
    first_accept = accepts[0]
    first_reject = rejects[0]
    assert result["frames"].index(first_reject) < result["frames"].index(first_accept)
    offers = frames_of(result, "offer")
    assert result["frames"].index(offers[0]) < result["frames"].index(first_accept)


def test_trade_counter_replaces_active_offer():
    def make_bots(seed):
        return [
            Scripted("Offerer", offerer_behavior({})),
            Scripted("Counterer", valid_player(counter_responder)),
            Scripted("Accepter", valid_player(accepting_responder)),
        ]

    _seed, result = run_until(
        lambda r: any(f["kind"] == "accept" and f["offered_by"] == 1 for f in r["frames"]),
        make_bots, cap=500,
    )
    counter = frames_of(result, "counter")[0]
    accept = next(f for f in frames_of(result, "accept") if f["offered_by"] == 1)
    assert accept["give"] == counter["give"] and accept["want"] == counter["want"]
    give_total = sum(counter["give"].values())
    want_total = sum(counter["want"].values())
    index = result["frames"].index(accept)
    before = result["frames"][index - 1]["counts"]
    # The counter author (seat 1) pays give and receives want.
    assert accept["counts"][1] == before[1] + want_total - give_total
    assert accept["counts"][2] == before[2] + give_total - want_total
    # The original offer (seat 0) was replaced, never executed.
    assert not any(f["kind"] == "accept" and f["offered_by"] == 0 for f in result["frames"])


def test_trade_max_three_offers_per_turn():
    def serial_offerer(observation):
        hand = observation["resources"]
        if observation["turn"]["type"] != "main":
            return {"type": "end_turn"}
        give = max(RESOURCES, key=lambda r: (hand[r], -RESOURCES.index(r)))
        if hand[give] < 1:
            return {"type": "end_turn"}
        want = min([r for r in RESOURCES if r != give],
                   key=lambda r: (hand[r], RESOURCES.index(r)))
        # Deliberately ignores the offers-used budget to test engine enforcement.
        return {"type": "offer", "give": {give: 1}, "want": {want: 1}}

    def make_bots(seed):
        return [
            Scripted("Serial", valid_player(serial_offerer)),
            Scripted("R1", valid_player(end_turn_or_reject)),
            Scripted("R2", valid_player(end_turn_or_reject)),
        ]

    _seed, result = run_until(
        lambda r: r["faults"][0] > 0 and any(f["kind"] == "offer" for f in r["frames"]),
        make_bots, cap=400,
    )
    # Walk the frames: between end_turns, seat 0 may open at most 3 offers.
    turn_offers, max_offers = 0, 0
    for frame in result["frames"]:
        if frame["kind"] == "end_turn":
            max_offers = max(max_offers, turn_offers)
            turn_offers = 0
        elif frame["kind"] == "offer":
            turn_offers += 1
    assert max_offers <= 3
    assert result["errors"][0] == "invalid main action"


def test_trade_counter_budget_enforced():
    def make_bots(seed):
        return [
            Scripted("Offerer", offerer_behavior({})),
            Scripted("C1", valid_player(counter_responder)),
            Scripted("C2", valid_player(counter_responder)),
            Scripted("C3", valid_player(counter_responder)),
        ]

    _seed, result = run_until(
        lambda r: sum(1 for f in r["frames"] if f["kind"] == "counter") >= 2
        and r["faults"][3] > 0,
        make_bots, cap=500, seeds=120,
    )
    counters = frames_of(result, "counter")
    # The first response round: one offer + counters; the fourth offer (a
    # counter past the budget of 3) must fault and fall back to reject.
    first_expired = frames_of(result, "trade_expired")[0]
    cutoff = result["frames"].index(first_expired)
    round_frames = result["frames"][:cutoff]
    assert sum(1 for f in round_frames if f["kind"] in ("offer", "counter")) == 3
    assert any(f["kind"] == "reject" and f["seat"] == 3 for f in round_frames)
    assert result["faults"][3] >= 1
    assert counters  # and the two legal counters went through


# -- robber ---------------------------------------------------------------------


def replayed_buildings(result):
    """Walk the privileged log once, yielding (robber_entry, buildings) per steal."""
    buildings: dict[int, tuple[int, str]] = {}
    board = build_board(random.Random(2))
    for entry in result["log"]:
        if entry["type"] == "build" and entry["built"] != "road":
            buildings[entry["id"]] = (entry["seat"], entry["built"])
        elif entry["type"] == "robber":
            yield entry, dict(buildings), board


def test_robber_on_seven_moves_and_steals_eligible_only():
    result = play_hexchange_match(baseline_table(4, 2), seed=2,
                                  decision_cap=2000, capture=True)
    robbers = log_of(result, "robber")
    assert robbers, "a long match must move the robber"
    for entry in robbers:
        assert entry["hex"] != entry["moved_from"]
        if entry["stole_from"] is not None:
            assert entry["victim_count"] > 7
    for entry, buildings, board in replayed_buildings(result):
        if entry["stole_from"] is None:
            continue
        adjacent = any(
            buildings.get(vertex) is not None
            and buildings[vertex][0] == entry["stole_from"]
            for vertex in board.hex_vertices(entry["hex"])
        )
        assert adjacent, "steal victims must border the new robber hex"
    # A roll of 7 never produces.
    for production in log_of(result, "production"):
        if not production.get("setup"):
            assert production["roll"] != 7


def test_ineligible_steal_faults_and_falls_back():
    def bad_robber(observation):
        kind = observation["turn"]["type"]
        seat = observation["seat"]
        if kind == "setup_settlement":
            return {"type": "build_settlement", "vertex": distance_spots(observation)[0]}
        if kind == "setup_road":
            return {"type": "build_road", "edge": setup_road_edge(observation, seat)}
        if kind == "robber":
            hex_id = next(h for h in range(len(observation["board"]["hexes"]))
                          if h != observation["robber"])
            # Try the poorest other seat: below the steal threshold early on,
            # so the attempt is ineligible and must fault into the deterministic
            # fallback.
            counts = {p["seat"]: p["count"] for p in observation["players"]}
            victim = min((s for s in counts if s != seat),
                         key=lambda s: (counts[s], s))
            return {"type": "move_robber", "hex": hex_id, "steal": victim}
        return end_turn_or_reject(observation)

    def make_bots(seed):
        return [
            Scripted("Bad", bad_robber),
            Scripted("S1", valid_player(end_turn_or_reject)),
            Scripted("S2", valid_player(end_turn_or_reject)),
        ]

    _seed, result = run_until(
        lambda r: r["faults"][0] > 0 and any(
            e["type"] == "robber" and e["seat"] == 0 for e in r["log"]),
        make_bots, cap=200,
    )
    assert result["errors"][0] == "invalid robber action"
    robber_events = [e for e in log_of(result, "robber") if e["seat"] == 0]
    assert robber_events
    for entry in robber_events:
        assert entry["hex"] != entry["moved_from"]
        if entry["stole_from"] is not None:
            assert entry["stole_from"] != 0
            assert entry["victim_count"] > 7


def test_stolen_token_hidden_from_observations_and_frames():
    recorders = [Recording(bot) for bot in baseline_table(4, 31)]
    result = play_hexchange_match(recorders, seed=31, decision_cap=800, capture=True)
    steals = [e for e in log_of(result, "robber") if e["stole_from"] is not None]
    assert steals, "the sweep must contain at least one steal"
    for entry in steals:
        assert entry["card"] in RESOURCES  # privileged log knows the token
    for recorder in recorders:
        for observation in recorder.seen:
            for event in observation["history"]:
                kind = event.get("type")
                if kind in ("dev_bought", "robber", "production", "roll"):
                    assert "card" not in event and "cards" not in event
                if kind == "robber":
                    assert set(event) <= {"type", "seat", "moved_from", "hex", "stole_from"}
                if kind == "dev_bought":
                    assert set(event) == {"type", "seat"}
                if kind == "production":
                    assert "cards" not in event
    for frame in result["frames"]:
        if frame["kind"] in ("robber", "dev_bought", "production", "roll"):
            assert "card" not in frame and "cards" not in frame
        if frame["kind"] == "robber":
            assert set(frame) <= {"kind", "counts", "seat", "moved_from", "hex", "stole_from"}
        if frame["kind"] == "dev_bought":
            assert set(frame) == {"kind", "counts", "seat"}


# -- development cards -------------------------------------------------------------


def test_dev_purchase_is_public_but_type_hidden():
    recorders = [Recording(bot) for bot in baseline_table(4, 3)]
    result = play_hexchange_match(recorders, seed=3, decision_cap=1500, capture=True)
    draws = log_of(result, "dev_draw")
    assert draws
    assert all(entry["card"] in DEV_TYPES for entry in draws)
    purchases = frames_of(result, "dev_bought")
    assert purchases
    for recorder in recorders:
        for observation in recorder.seen:
            assert "deck" not in observation and "dev_deck" not in observation
            for event in observation["history"]:
                if event.get("type") == "dev_bought":
                    assert set(event) == {"type", "seat"}


def test_one_dev_per_turn_and_never_the_just_bought_one():
    for seed in (1, 2, 3):
        result = play_hexchange_match(baseline_table(4, seed), seed=seed,
                                      decision_cap=3000, capture=False)
        played_in_turn = 0
        drew_this_turn_by_seat = {}
        for entry in result["log"]:
            if entry["type"] == "end_turn":
                played_in_turn = 0
                drew_this_turn_by_seat.clear()
            elif entry["type"] == "dev_draw":
                drew_this_turn_by_seat[entry["seat"]] = True
            elif entry["type"] == "dev_played":
                assert played_in_turn == 0  # one dev card per turn
                played_in_turn += 1
                assert not drew_this_turn_by_seat.get(entry["seat"])


def test_dev_card_effects_across_baseline_sweep():
    seen_draws, knight_robber, road_pairs, monopolies, plenties = set(), 0, 0, 0, 0
    for seed in (1, 2, 3, 4):
        result = play_hexchange_match(baseline_table(4, seed), seed=seed,
                                      decision_cap=3000, capture=True)
        seen_draws.update(entry["card"] for entry in log_of(result, "dev_draw"))
        frames = result["frames"]
        for index, frame in enumerate(frames):
            if frame["kind"] != "dev_played":
                continue
            if frame["card"] == "knight":
                later = [f for f in frames[index + 1:index + 4]
                         if f["kind"] == "robber" and f["seat"] == frame["seat"]]
                assert later, "a knight must be followed by a robber move"
                knight_robber += 1
            elif frame["card"] == "monopoly":
                before = frames[index - 1]["counts"]
                assert frame["counts"][frame["seat"]] - before[frame["seat"]] == \
                    sum(frame["took"])
                for seat, taken in enumerate(frame["took"]):
                    if seat != frame["seat"]:
                        assert before[seat] - frame["counts"][seat] == taken
                monopolies += 1
            elif frame["card"] == "year_of_plenty":
                before = frames[index - 1]["counts"]
                assert frame["counts"][frame["seat"]] - before[frame["seat"]] == 2
                plenties += 1
        # road-building: two free roads, unless no edge was placeable (forfeit).
        entries = result["log"]
        for index, entry in enumerate(entries):
            if entry["type"] != "dev_played" or entry["card"] != "road_building":
                continue
            following = []
            for later in entries[index + 1:]:
                if later["type"] == "end_turn":
                    break
                following.append(later)
            free_roads = [e for e in following
                          if e["type"] == "build" and e["built"] == "road" and e["free"]]
            skipped = any(e["type"] == "free_road_skipped" for e in following)
            assert len(free_roads) == 2 or skipped
            if len(free_roads) == 2:
                road_pairs += 1
    assert seen_draws == set(DEV_TYPES)
    assert knight_robber >= 1 and road_pairs >= 1 and monopolies >= 1 and plenties >= 1


def test_vp_dev_card_can_complete_the_win(monkeypatch):
    monkeypatch.setattr(hex_engine, "VP_TARGET", 3)

    def buyer(observation):
        turn = observation["turn"]
        seat = observation["seat"]
        kind = turn["type"]
        if kind == "setup_settlement":
            return {"type": "build_settlement", "vertex": distance_spots(observation)[0]}
        if kind == "setup_road":
            return {"type": "build_road", "edge": setup_road_edge(observation, seat)}
        if kind == "robber":
            hex_id = next(h for h in range(len(observation["board"]["hexes"]))
                          if h != observation["robber"])
            return {"type": "move_robber", "hex": hex_id, "steal": None}
        if kind == "respond":
            return {"type": "reject"}
        hand = observation["resources"]
        if all(hand[r] >= c for r, c in COSTS["dev"].items()) and \
                observation["dev_cards"]["vp"] == 0:
            return {"type": "buy_dev"}
        missing = [r for r in RESOURCES if hand[r] < COSTS["dev"].get(r, 0)]
        if missing:
            want = min(missing, key=lambda r: (hand[r], RESOURCES.index(r)))
            rich = [r for r in RESOURCES if hand[r] >= 4 and r != want]
            if rich:
                give = max(rich, key=lambda r: (hand[r], -RESOURCES.index(r)))
                return {"type": "bank_trade", "give": {give: 4}, "want": {want: 1}}
        return {"type": "end_turn"}

    def make_bots(seed):
        return [
            Scripted("Buyer", buyer),
            Scripted("S1", valid_player(end_turn_or_reject)),
            Scripted("S2", valid_player(end_turn_or_reject)),
        ]

    _seed, result = run_until(
        lambda r: r["terminal_reason"] == "win" and r["winner_seats"] == [0],
        make_bots, cap=600, seeds=8,
    )
    assert result["points"][0] == 3
    assert result["match_points"] == [1.0, 0.0, 0.0]
    # The winner held the victory-point card; public VP never showed it.
    end = log_of(result, "end")[-1]
    assert end["dev_hands"][0]["vp"] >= 1
    vp_plays = [e for e in log_of(result, "dev_played")
                if e["card"] == "vp" and e["seat"] == 0]
    assert vp_plays == []  # VP cards are never played


# -- termination ---------------------------------------------------------------------


def test_ten_vp_win_terminates_match():
    for seed in (2, 4, 9):
        result = play_hexchange_match(baseline_table(4, seed), seed=seed,
                                      decision_cap=3000, capture=False)
        assert result["terminal_reason"] == "win"
        winner = result["winner_seats"][0]
        assert result["points"][winner] == 10
        assert result["match_points"][winner] == 1.0
        assert sum(1.0 for p in result["match_points"] if p) == 1.0


def test_cap_most_vp_wins_and_ties_share():
    for seats, cap, share in ((4, 16, 0.25), (3, 12, 1 / 3)):
        result = play_hexchange_match(baseline_table(seats, 1), seed=1,
                                      decision_cap=cap, capture=True)
        assert result["terminal_reason"] == "cap"
        assert result["points"] == [2] * seats  # setup settlements only
        assert result["winner_seats"] == list(range(seats))
        assert result["match_points"] == [share] * seats
        assert result["decisions"] == cap


def test_cap_picks_leaders_when_vps_differ():
    result = play_hexchange_match(baseline_table(4, 1), seed=1,
                                  decision_cap=400, capture=False)
    assert result["terminal_reason"] == "cap"
    best = max(result["points"])
    assert result["winner_seats"] == [
        i for i, vp in enumerate(result["points"]) if vp == best
    ]


# -- fallbacks and validation ----------------------------------------------------------


def test_garbage_bot_fallbacks_and_sandbox_down_propagates():
    bots = [Garbage(), Garbage(), Garbage()]
    result = play_hexchange_match(bots, seed=17, decision_cap=60, capture=True)
    assert result["terminal_reason"] == "cap"
    assert all(faults >= 1 for faults in result["faults"])
    assert all(error == "invalid setup_settlement action" for error in result["errors"])
    # Fallbacks still placed a full legal setup for every seat.
    for seat in range(3):
        builds = [e for e in log_of(result, "build") if e["seat"] == seat and e["free"]]
        assert [e["built"] for e in builds] == ["settlement", "road",
                                                "settlement", "road"]

    class PartialGarbage(Garbage):
        name = "Partial"

        def act(self, observation):
            if observation["turn"]["type"] == "setup_settlement":
                return {"type": "build_settlement",
                        "vertex": distance_spots(observation)[0]}
            return {"type": "explode"}

    bots = [PartialGarbage(), Scripted("S1", valid_player(end_turn_or_reject)),
            Scripted("S2", valid_player(end_turn_or_reject))]
    result = play_hexchange_match(bots, seed=18, decision_cap=120, capture=True)
    assert result["faults"][0] >= 1
    assert result["errors"][0] == "invalid setup_road action"

    with pytest.raises(SandboxDown):
        play_hexchange_match([Down(), Scripted("S1", valid_player(end_turn_or_reject)),
                              Scripted("S2", valid_player(end_turn_or_reject))],
                             seed=19)

    class BadReset:
        name = "BadReset"

        def reset(self):
            raise SandboxDown("unavailable")

        def act(self, observation):
            raise AssertionError("must never be asked")

    with pytest.raises(SandboxDown):
        play_hexchange_match([BadReset(), Scripted("S1", valid_player(end_turn_or_reject)),
                              Scripted("S2", valid_player(end_turn_or_reject))],
                             seed=20)


def test_seat_count_and_cap_validation():
    with pytest.raises(ValueError):
        play_hexchange_match([Garbage(), Garbage()], seed=1)
    with pytest.raises(ValueError):
        play_hexchange_match([Garbage()] * 5, seed=1)
    with pytest.raises(ValueError):
        play_hexchange_match([Garbage()] * 3, seed=1, decision_cap=0)
    with pytest.raises(ValueError):
        play_hexchange_match([Garbage()] * 3, seed=1, decision_cap=100_001)


def test_per_seat_and_shared_piece_caps(monkeypatch):
    monkeypatch.setattr(hex_engine, "PER_SEAT_ROADS", 3)
    result = play_hexchange_match(baseline_table(4, 5), seed=5,
                                  decision_cap=1200, capture=False)
    for seat in range(4):
        roads = sum(1 for e in log_of(result, "build")
                    if e["built"] == "road" and e["seat"] == seat)
        assert roads <= 3

    monkeypatch.setattr(hex_engine, "PER_SEAT_ROADS", 15)
    monkeypatch.setattr(hex_engine, "SETTLEMENT_SUPPLY", 10)
    result = play_hexchange_match(baseline_table(4, 5), seed=5,
                                  decision_cap=2000, capture=False)
    placed, upgrades = 0, 0
    for entry in log_of(result, "build"):
        if entry["built"] == "settlement":
            placed += 1
        elif entry["built"] == "city":
            upgrades += 1
    assert placed <= 10 + upgrades  # the shared settlement supply binds


# -- determinism, privacy, and schema ----------------------------------------------------


def test_deterministic_replay_from_seed_and_bots():
    first = play_hexchange_match(baseline_table(4, 99), seed=123, capture=True)
    second = play_hexchange_match(baseline_table(4, 99), seed=123, capture=True)
    assert first["points"] == second["points"]
    assert first["match_points"] == second["match_points"]
    assert first["decisions"] == second["decisions"]
    assert first["winner_seats"] == second["winner_seats"]
    assert [e["type"] for e in first["log"]] == [e["type"] for e in second["log"]]
    assert first["frames"] == second["frames"]
    third = play_hexchange_match(baseline_table(4, 99), seed=124, capture=False)
    assert third["points"] != first["points"] or third["decisions"] != first["decisions"]


def test_observations_never_leak_hidden_state():
    recorders = [Recording(bot) for bot in baseline_table(4, 6)]
    play_hexchange_match(recorders, seed=6, decision_cap=400, capture=True)
    expected_keys = {
        "protocol", "game", "rules_version", "seat", "players", "board", "robber",
        "buildings", "roads", "resources", "dev_cards", "turn", "history",
        "decision_number", "decision_cap",
    }
    for recorder in recorders:
        for observation in recorder.seen:
            assert set(observation) == expected_keys
            assert observation["game"] == "hexchange" and observation["protocol"] == 1
            for player in observation["players"]:
                assert set(player) == {"seat", "name", "count", "vp"}
            mine = observation["players"][observation["seat"]]
            assert sum(observation["resources"].values()) == mine["count"]
            assert set(observation["resources"]) == set(RESOURCES)
            assert set(observation["dev_cards"]) == set(DEV_TYPES)


def test_result_schema_and_replay_envelope():
    result = play_hexchange_match(baseline_table(3, 8), seed=8,
                                  decision_cap=300, capture=True)
    required = {
        "points", "match_points", "winner_seats", "terminal_reason", "faults",
        "errors", "hands", "matches", "decisions", "names", "log", "frames",
        "replay",
    }
    assert required <= set(result)
    assert result["hands"] == 1 and result["matches"] == 1
    assert len(result["points"]) == 3 and len(result["faults"]) == 3
    assert isinstance(result["frames"], list) and result["frames"]
    envelope = result["replay"]
    assert envelope["game"] == "hexchange"
    assert envelope["protocol"] == 1
    assert envelope["names"] == result["names"] == ["Expander", "Trader", "RobberHater"]
    assert envelope["frames"] is result["frames"] or envelope["frames"] == result["frames"]
    assert result["frames"][-1]["kind"] == "end"
    assert result["frames"][-1]["winner_seats"] == result["winner_seats"]
    # The privileged log may carry hidden state the frames never do.
    assert any(e["type"] == "dev_draw" and "card" in e for e in result["log"])


def test_baselines_complete_matches_with_trades_and_robbers():
    accepted, robbers = 0, 0
    for seed in (1, 2, 3, 4):
        for seats in (3, 4):
            result = play_hexchange_match(baseline_table(seats, seed), seed=seed,
                                          decision_cap=500, capture=False)
            assert result["terminal_reason"] in ("win", "cap")
            assert result["decisions"] <= 500
            assert sum(result["faults"]) == 0, result["errors"]
            accepted += sum(1 for e in result["log"] if e["type"] == "accept")
            robbers += sum(1 for e in result["log"] if e["type"] == "robber")
    assert accepted >= 1, "across the seeds at least one trade must be accepted"
    assert robbers >= 1, "across the seeds at least one robber move must happen"


def test_baseline_factory_bounds():
    assert hex_baselines.make_hexchange_baselines(0) == []
    with pytest.raises(ValueError):
        hex_baselines.make_hexchange_baselines(4)
    with pytest.raises(ValueError):
        hex_baselines.make_hexchange_table(2)
    with pytest.raises(ValueError):
        hex_baselines.make_hexchange_table(5)
