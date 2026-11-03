"""Stack Theory Hexchange v1 — deterministic hex-island trading engine.

Inspired by the classic hex-island trading board game (see ``RULES.md`` for
the inspiration citation, the full rules, and every declared v1 deviation).
Written to the frozen contract in ``GAMES_CONTRACT.md`` section 12: the turn
loop, the structured trade overlay (``offer`` / ``accept`` / ``reject`` /
``counter``, at most three offers per turn), the visibility table, fault
fallbacks, and the result/replay shapes.

Deterministic given (bots, seed): the island, its number tokens, the
development deck, and both dice flow from one seeded RNG, and every agent
decision either succeeds or falls back along a fixed rule. Hidden state —
resource identities, the development deck, opponents' dev cards, the stolen
token — never enters an observation or a public replay frame.
"""
from __future__ import annotations

import copy
import random

from ...sandbox import SandboxDown
from .board import (
    CITY_SUPPLY,
    COSTS,
    PER_SEAT_CITIES,
    PER_SEAT_ROADS,
    PER_SEAT_SETTLEMENTS,
    RESOURCE_TYPES,
    ROAD_SUPPLY,
    SETTLEMENT_SUPPLY,
    board_view,
    build_board,
    can_afford,
    empty_hand,
    hand_total,
    move_resources,
    pay_cost,
    valid_resource_map,
)

PROTOCOL = 1
GAME_ID = "hexchange"
RULES_VERSION = 1
SEATS = (3, 4)
DECISION_CAP = 500
VP_TARGET = 10
MAX_OFFERS = 3
BANK_GIVE = 4
BANK_WANT = 1
STEAL_THRESHOLD = 7
HISTORY_DEPTH = 100

DEV_TYPES = ("knight", "vp", "monopoly", "road_building", "year_of_plenty")
DEV_DECK = (
    ["knight"] * 14 + ["vp"] * 5 + ["monopoly"] * 2
    + ["road_building"] * 2 + ["year_of_plenty"] * 2
)


def play_hexchange_match(
    bots: list,
    seed: int,
    decision_cap: int = DECISION_CAP,
    capture: bool = False,
) -> dict:
    n = len(bots)
    if n not in SEATS:
        raise ValueError("Hexchange v1 is played with 3 or 4 seats.")
    if not 1 <= decision_cap <= 100_000:
        raise ValueError("decision_cap must be between 1 and 100000.")

    rng = random.Random(seed)
    board = build_board(rng)
    names = [str(getattr(bot, "name", f"Seat {i + 1}")) for i, bot in enumerate(bots)]
    board_public = board_view(board)

    hex_numbers = [entry["number"] for entry in board.hexes]
    hex_terrains = [entry["terrain"] for entry in board.hexes]
    hex_vertex_list = [entry["vertices"] for entry in board.hexes]
    adj_vertices = [entry["vertices"] for entry in board.vertices]
    incident_edges = [entry["edges"] for entry in board.vertices]
    edge_ends = [entry["vertices"] for entry in board.edges]

    hands = [empty_hand() for _ in range(n)]
    dev_hands = [{dev: 0 for dev in DEV_TYPES} for _ in range(n)]
    dev_deck = list(DEV_DECK)
    rng.shuffle(dev_deck)
    just_bought = [set() for _ in range(n)]

    roads: dict[int, int] = {}                      # edge id -> seat
    buildings: dict[int, tuple[int, str]] = {}      # vertex id -> (seat, kind)
    robber = board.desert_hex
    road_counts = [0] * n
    settlement_counts = [0] * n
    city_counts = [0] * n
    supply = {"road": ROAD_SUPPLY, "settlement": SETTLEMENT_SUPPLY, "city": CITY_SUPPLY}
    vp = [0] * n                                    # public building VP

    faults = [0] * n
    errors: list[str | None] = [None] * n
    reset_failed = [False] * n
    for seat, bot in enumerate(bots):
        try:
            bot.reset()
        except SandboxDown:
            raise
        except Exception as exc:  # noqa: BLE001 — every bot failure is a fault
            faults[seat] += 1
            errors[seat] = str(exc)[:200]
            reset_failed[seat] = True

    decision_number = 0
    frames: list[dict] = []
    log: list[dict] = []
    history: list[dict] = []
    winner_seats: list[int] | None = None
    terminal: str | None = None

    # Mutable turn state.
    active = 0
    state = "setup_settlement"
    setup_order = list(range(n)) + list(range(n - 1, -1, -1))
    setup_pointer = 0
    setup_round = 1
    last_setup_vertex: int | None = None
    offers_used = 0
    pending_trade: dict | None = None
    free_roads = 0
    dev_played_this_turn = False

    def counts() -> list[int]:
        return [hand_total(hand) for hand in hands]

    def pub(event: dict) -> None:
        history.append(event)

    def frame(kind: str, **fields) -> None:
        if capture:
            frames.append({"kind": kind, "counts": counts(), **fields})

    def record(event: dict) -> None:
        log.append(event)  # privileged audit: may carry hidden state

    def observation(seat: int, turn: dict) -> dict:
        players = [
            {"seat": i, "name": names[i], "count": hand_total(hands[i]), "vp": vp[i]}
            for i in range(n)
        ]
        return {
            "protocol": PROTOCOL,
            "game": GAME_ID,
            "rules_version": RULES_VERSION,
            "seat": seat,
            "players": players,
            "board": copy.deepcopy(board_public),
            "robber": robber,
            "buildings": [
                {"seat": occupant[0], "vertex": vertex, "kind": occupant[1]}
                for vertex, occupant in sorted(buildings.items())
            ],
            "roads": [{"seat": owner, "edge": edge} for edge, owner in sorted(roads.items())],
            "resources": dict(hands[seat]),
            "dev_cards": dict(dev_hands[seat]),
            "turn": copy.deepcopy(turn),
            "history": copy.deepcopy(history[-HISTORY_DEPTH:]),
            "decision_number": decision_number + 1,
            "decision_cap": decision_cap,
        }

    def decide(seat: int, turn: dict, fallback: dict, validate) -> tuple[dict, bool]:
        """Collect one decision; faults fall back deterministically."""
        nonlocal decision_number
        decision_number += 1
        if reset_failed[seat]:
            return dict(fallback), True
        try:
            raw = bots[seat].act(observation(seat, turn))
        except SandboxDown:
            raise
        except Exception as exc:  # noqa: BLE001 — timeout/crash/transport fault
            faults[seat] += 1
            if errors[seat] is None:
                errors[seat] = str(exc)[:200]
            return dict(fallback), True
        checked = validate(raw if type(raw) is dict else None)
        if checked is None:
            faults[seat] += 1
            if errors[seat] is None:
                errors[seat] = "invalid " + str(turn["type"]) + " action"
            return dict(fallback), True
        return checked, False

    # -- placement legality -------------------------------------------------

    def connects(seat: int, vertex: int) -> bool:
        occupant = buildings.get(vertex)
        if occupant is not None:
            return occupant[0] == seat
        return any(roads.get(edge) == seat for edge in incident_edges[vertex])

    def road_placeable(seat: int, edge: int) -> bool:
        if edge in roads or supply["road"] <= 0 or road_counts[seat] >= PER_SEAT_ROADS:
            return False
        a, b = edge_ends[edge]
        return connects(seat, a) or connects(seat, b)

    def settlement_spot_open(vertex: int) -> bool:
        return vertex not in buildings and all(
            other not in buildings for other in adj_vertices[vertex]
        )

    def settlement_placeable(seat: int, vertex: int) -> bool:
        if not settlement_spot_open(vertex):
            return False
        if supply["settlement"] <= 0 or settlement_counts[seat] >= PER_SEAT_SETTLEMENTS:
            return False
        return any(roads.get(edge) == seat for edge in incident_edges[vertex])

    def city_placeable(seat: int, vertex: int) -> bool:
        if buildings.get(vertex) != (seat, "settlement"):
            return False
        return supply["city"] > 0 and city_counts[seat] < PER_SEAT_CITIES

    # -- deterministic fallbacks ---------------------------------------------

    def first_settlement_spot() -> int | None:
        for vertex in range(len(board.vertices)):
            if settlement_spot_open(vertex):
                return vertex
        return None

    def first_setup_road() -> int | None:
        if last_setup_vertex is None:
            return None
        for edge in incident_edges[last_setup_vertex]:
            if edge not in roads:
                return edge
        return None

    def first_road(seat: int) -> int | None:
        for edge in range(len(board.edges)):
            if road_placeable(seat, edge):
                return edge
        return None

    def first_robber_hex() -> int:
        for hex_id in range(len(board.hexes)):
            if hex_id != robber:
                return hex_id
        raise RuntimeError("the robber has nowhere to move")  # unreachable: 19 hexes

    def steal_targets(hex_id: int, mover: int) -> list[int]:
        targets = set()
        for vertex in hex_vertex_list[hex_id]:
            occupant = buildings.get(vertex)
            if (
                occupant is not None and occupant[0] != mover
                and hand_total(hands[occupant[0]]) > STEAL_THRESHOLD
            ):
                targets.add(occupant[0])
        return sorted(targets)

    # -- validators ------------------------------------------------------------

    def _vertex_id(value) -> int | None:
        if type(value) is int and 0 <= value < len(board.vertices):
            return value
        return None

    def _edge_id(value) -> int | None:
        if type(value) is int and 0 <= value < len(board.edges):
            return value
        return None

    def validate_setup_settlement(action) -> dict | None:
        if action is None or action.get("type") != "build_settlement":
            return None
        vertex = _vertex_id(action.get("vertex"))
        if vertex is None or not settlement_spot_open(vertex):
            return None
        return {"type": "build_settlement", "vertex": vertex}

    def validate_setup_road(action) -> dict | None:
        if action is None or action.get("type") != "build_road":
            return None
        edge = _edge_id(action.get("edge"))
        if edge is None or edge in roads or last_setup_vertex is None:
            return None
        if last_setup_vertex not in edge_ends[edge]:
            return None
        return {"type": "build_road", "edge": edge}

    def validate_robber(action) -> dict | None:
        if action is None or action.get("type") != "move_robber":
            return None
        hex_id = action.get("hex")
        if type(hex_id) is not int or not 0 <= hex_id < len(board.hexes) or hex_id == robber:
            return None
        steal = action.get("steal", None)
        if steal is not None and (
            type(steal) is not int or steal not in steal_targets(hex_id, active)
        ):
            return None
        return {"type": "move_robber", "hex": hex_id, "steal": steal}

    def validate_free_road(action) -> dict | None:
        if action is None or action.get("type") != "build_road":
            return None
        edge = _edge_id(action.get("edge"))
        if edge is None or not road_placeable(active, edge):
            return None
        return {"type": "build_road", "edge": edge}

    def validate_main(action) -> dict | None:
        if action is None:
            return None
        seat = active
        hand = hands[seat]
        kind = action.get("type")
        if kind == "end_turn":
            return {"type": "end_turn"}
        if kind == "build_road":
            edge = _edge_id(action.get("edge"))
            if edge is None or not road_placeable(seat, edge):
                return None
            if not can_afford(hand, COSTS["road"]):
                return None
            return {"type": "build_road", "edge": edge}
        if kind == "build_settlement":
            vertex = _vertex_id(action.get("vertex"))
            if vertex is None or not settlement_placeable(seat, vertex):
                return None
            if not can_afford(hand, COSTS["settlement"]):
                return None
            return {"type": "build_settlement", "vertex": vertex}
        if kind == "build_city":
            vertex = _vertex_id(action.get("vertex"))
            if vertex is None or not city_placeable(seat, vertex):
                return None
            if not can_afford(hand, COSTS["city"]):
                return None
            return {"type": "build_city", "vertex": vertex}
        if kind == "buy_dev":
            if not dev_deck or not can_afford(hand, COSTS["dev"]):
                return None
            return {"type": "buy_dev"}
        if kind == "play_dev":
            if dev_played_this_turn:
                return None
            card = action.get("card")
            if type(card) is not str or card not in DEV_TYPES or card == "vp":
                return None
            if dev_hands[seat][card] <= 0 or card in just_bought[seat]:
                return None
            if card == "monopoly":
                resource = action.get("resource")
                if type(resource) is not str or resource not in RESOURCE_TYPES:
                    return None
                return {"type": "play_dev", "card": card, "resource": resource}
            if card == "year_of_plenty":
                picks = action.get("resources")
                if type(picks) is not list or len(picks) != 2:
                    return None
                for pick in picks:
                    if type(pick) is not str or pick not in RESOURCE_TYPES:
                        return None
                return {"type": "play_dev", "card": card, "resources": list(picks)}
            if card in ("knight", "road_building"):
                return {"type": "play_dev", "card": card}
            return None
        if kind == "offer":
            if offers_used >= MAX_OFFERS:
                return None
            give = valid_resource_map(action.get("give"))
            want = valid_resource_map(action.get("want"))
            if give is None or want is None or not can_afford(hand, give):
                return None
            return {"type": "offer", "give": give, "want": want}
        if kind == "bank_trade":
            give = valid_resource_map(action.get("give"))
            want = valid_resource_map(action.get("want"))
            if give is None or want is None:
                return None
            if len(give) != 1 or next(iter(give.values())) != BANK_GIVE:
                return None
            if len(want) != 1 or next(iter(want.values())) != BANK_WANT:
                return None
            if next(iter(give)) == next(iter(want)) or not can_afford(hand, give):
                return None
            return {"type": "bank_trade", "give": give, "want": want}
        return None

    def validate_respond(action) -> dict | None:
        if action is None or pending_trade is None:
            return None
        seat = pending_trade["queue"][0]
        kind = action.get("type")
        if kind == "reject":
            return {"type": "reject"}
        if kind == "accept":
            if not can_afford(hands[seat], pending_trade["want"]):
                return None
            return {"type": "accept"}
        if kind == "counter":
            give = valid_resource_map(action.get("give"))
            want = valid_resource_map(action.get("want"))
            if give is None or want is None or offers_used >= MAX_OFFERS:
                return None
            if not can_afford(hands[seat], give):
                return None
            return {"type": "counter", "give": give, "want": want}
        return None

    # -- state transitions ------------------------------------------------------

    def check_win(seat: int) -> None:
        nonlocal winner_seats, terminal
        if winner_seats is None and vp[seat] + dev_hands[seat]["vp"] >= VP_TARGET:
            winner_seats = [seat]
            terminal = "win"

    def begin_turn(seat: int) -> None:
        nonlocal active, offers_used, dev_played_this_turn, state
        active = seat
        offers_used = 0
        dev_played_this_turn = False
        just_bought[seat].clear()
        dice = [rng.randint(1, 6), rng.randint(1, 6)]
        roll = dice[0] + dice[1]
        pub({"type": "roll", "seat": seat, "dice": dice})
        record({"type": "roll", "seat": seat, "dice": dice})
        frame("roll", seat=seat, dice=dice)
        if roll == 7:
            state = "robber"
        else:
            produce(roll)
            state = "main"

    def produce(roll: int) -> None:
        produced = [
            hex_id for hex_id in range(len(board.hexes))
            if hex_numbers[hex_id] == roll and hex_id != robber
        ]
        gains = [empty_hand() for _ in range(n)]
        for hex_id in produced:
            resource = hex_terrains[hex_id]
            for vertex in hex_vertex_list[hex_id]:
                occupant = buildings.get(vertex)
                if occupant is None:
                    continue
                gains[occupant[0]][resource] += 2 if occupant[1] == "city" else 1
        for seat in range(n):
            for resource, amount in gains[seat].items():
                hands[seat][resource] += amount
        totals = [sum(gain.values()) for gain in gains]
        pub({"type": "production", "roll": roll, "hexes": produced, "gained": totals})
        record({
            "type": "production", "roll": roll, "hexes": produced, "gained": totals,
            "cards": [{k: v for k, v in gain.items() if v} for gain in gains],
        })
        frame("production", roll=roll, hexes=produced, gained=totals)

    def setup_production(seat: int, vertex: int) -> None:
        gained = empty_hand()
        for hex_id in board.vertex_hexes(vertex):
            if hex_numbers[hex_id] is not None:
                gained[hex_terrains[hex_id]] += 1
        for resource, amount in gained.items():
            hands[seat][resource] += amount
        totals = [0] * n
        totals[seat] = sum(gained.values())
        pub({"type": "production", "setup": True, "seat": seat, "gained": totals})
        record({
            "type": "production", "setup": True, "seat": seat, "gained": totals,
            "cards": {k: v for k, v in gained.items() if v},
        })
        frame("production", setup=True, seat=seat, gained=totals)

    def place_settlement(seat: int, vertex: int, free: bool) -> None:
        if not free:
            pay_cost(hands[seat], COSTS["settlement"])
        buildings[vertex] = (seat, "settlement")
        supply["settlement"] -= 1
        settlement_counts[seat] += 1
        vp[seat] += 1
        pub({"type": "build", "seat": seat, "built": "settlement", "id": vertex, "free": free})
        record({"type": "build", "seat": seat, "built": "settlement", "id": vertex,
                "free": free, "hand": dict(hands[seat])})
        frame("build", seat=seat, built="settlement", id=vertex, free=free)
        check_win(seat)

    def place_city(seat: int, vertex: int) -> None:
        pay_cost(hands[seat], COSTS["city"])
        buildings[vertex] = (seat, "city")
        supply["city"] -= 1
        city_counts[seat] += 1
        supply["settlement"] += 1
        settlement_counts[seat] -= 1
        vp[seat] += 1
        pub({"type": "build", "seat": seat, "built": "city", "id": vertex, "free": False})
        record({"type": "build", "seat": seat, "built": "city", "id": vertex,
                "free": False, "hand": dict(hands[seat])})
        frame("build", seat=seat, built="city", id=vertex, free=False)
        check_win(seat)

    def place_road(seat: int, edge: int, free: bool) -> None:
        if not free:
            pay_cost(hands[seat], COSTS["road"])
        roads[edge] = seat
        supply["road"] -= 1
        road_counts[seat] += 1
        pub({"type": "build", "seat": seat, "built": "road", "id": edge, "free": free})
        record({"type": "build", "seat": seat, "built": "road", "id": edge,
                "free": free, "hand": dict(hands[seat])})
        frame("build", seat=seat, built="road", id=edge, free=free)

    def apply_robber(seat: int, hex_id: int, target: int | None) -> None:
        nonlocal robber
        moved_from = robber
        robber = hex_id
        stolen = None
        if target is not None:
            pool = [resource for resource, count in hands[target].items() for _ in range(count)]
            stolen = rng.choice(pool)
            hands[target][stolen] -= 1
            hands[seat][stolen] += 1
        pub({"type": "robber", "seat": seat, "moved_from": moved_from,
             "hex": hex_id, "stole_from": target})
        record({
            "type": "robber", "seat": seat, "moved_from": moved_from,
            "hex": hex_id, "stole_from": target, "card": stolen,
            "victim_count": hand_total(hands[target]) if target is not None else None,
        })
        frame("robber", seat=seat, moved_from=moved_from, hex=hex_id, stole_from=target)

    def advance_setup() -> None:
        nonlocal setup_pointer, setup_round, state
        setup_pointer += 1
        if setup_pointer >= 2 * n:
            begin_turn(0)
            return
        if setup_pointer == n:
            setup_round = 2
        state = "setup_settlement"

    def run_trade_step() -> None:
        nonlocal pending_trade, offers_used, state
        trade = pending_trade
        seat = trade["queue"][0]
        turn = {
            "type": "respond",
            "offer": {"give": dict(trade["give"]), "want": dict(trade["want"])},
            "offered_by": trade["author"],
            "offers_used": offers_used,
        }
        action, _ = decide(seat, turn, {"type": "reject"}, validate_respond)
        kind = action["type"]
        if kind == "accept":
            author = trade["author"]
            move_resources(hands[author], hands[seat], trade["give"])
            move_resources(hands[seat], hands[author], trade["want"])
            pub({"type": "accept", "seat": seat, "offered_by": author,
                 "give": trade["give"], "want": trade["want"]})
            record({"type": "accept", "seat": seat, "offered_by": author,
                    "give": trade["give"], "want": trade["want"],
                    "hands_after": [dict(hand) for hand in hands]})
            frame("accept", seat=seat, offered_by=author,
                  give=trade["give"], want=trade["want"])
            pending_trade = None
            state = "main"
        elif kind == "counter":
            offers_used += 1
            pub({"type": "counter", "seat": seat, "give": action["give"], "want": action["want"]})
            record({"type": "counter", "seat": seat, "give": action["give"],
                    "want": action["want"]})
            frame("counter", seat=seat, give=action["give"], want=action["want"])
            pending_trade = {
                "author": seat, "give": action["give"], "want": action["want"],
                "queue": [(seat + k) % n for k in range(1, n)],
            }
        else:  # reject
            trade["queue"].pop(0)
            pub({"type": "reject", "seat": seat})
            record({"type": "reject", "seat": seat})
            frame("reject", seat=seat)
            if not trade["queue"]:
                pub({"type": "trade_expired", "seat": trade["author"]})
                record({"type": "trade_expired", "seat": trade["author"]})
                frame("trade_expired", seat=trade["author"])
                pending_trade = None
                state = "main"

    def run_main_step() -> None:
        nonlocal offers_used, pending_trade, free_roads, dev_played_this_turn, state
        seat = active
        turn = {"type": "main", "offers_used": offers_used, "offers_max": MAX_OFFERS}
        action, _ = decide(seat, turn, {"type": "end_turn"}, validate_main)
        kind = action["type"]
        if kind == "end_turn":
            pub({"type": "end_turn", "seat": seat})
            record({"type": "end_turn", "seat": seat, "hand": dict(hands[seat])})
            frame("end_turn", seat=seat)
            begin_turn((seat + 1) % n)
        elif kind == "build_road":
            place_road(seat, action["edge"], free=False)
        elif kind == "build_settlement":
            place_settlement(seat, action["vertex"], free=False)
        elif kind == "build_city":
            place_city(seat, action["vertex"])
        elif kind == "buy_dev":
            pay_cost(hands[seat], COSTS["dev"])
            card = dev_deck.pop(0)
            dev_hands[seat][card] += 1
            just_bought[seat].add(card)
            pub({"type": "dev_bought", "seat": seat})
            record({"type": "dev_draw", "seat": seat, "card": card, "remaining": len(dev_deck)})
            frame("dev_bought", seat=seat)
            check_win(seat)
        elif kind == "play_dev":
            card = action["card"]
            dev_hands[seat][card] -= 1
            dev_played_this_turn = True
            if card == "knight":
                pub({"type": "dev_played", "seat": seat, "card": card})
                record({"type": "dev_played", "seat": seat, "card": card})
                frame("dev_played", seat=seat, card=card)
                state = "robber"
            elif card == "monopoly":
                resource = action["resource"]
                taken = [0] * n
                for other in range(n):
                    if other == seat:
                        continue
                    taken[other] = hands[other][resource]
                    hands[other][resource] = 0
                hands[seat][resource] += sum(taken)
                pub({"type": "dev_played", "seat": seat, "card": card,
                     "resource": resource, "took": taken})
                record({"type": "dev_played", "seat": seat, "card": card,
                        "resource": resource, "took": taken})
                frame("dev_played", seat=seat, card=card, resource=resource, took=taken)
            elif card == "road_building":
                pub({"type": "dev_played", "seat": seat, "card": card})
                record({"type": "dev_played", "seat": seat, "card": card})
                frame("dev_played", seat=seat, card=card)
                if first_road(seat) is not None:
                    free_roads = 2
                    state = "free_road"
                else:
                    record({"type": "free_road_skipped", "seat": seat})
            elif card == "year_of_plenty":
                picks = action["resources"]
                for resource in picks:
                    hands[seat][resource] += 1
                pub({"type": "dev_played", "seat": seat, "card": card, "resources": picks})
                record({"type": "dev_played", "seat": seat, "card": card, "resources": picks})
                frame("dev_played", seat=seat, card=card, resources=picks)
        elif kind == "offer":
            offers_used += 1
            pending_trade = {
                "author": seat, "give": action["give"], "want": action["want"],
                "queue": [(seat + k) % n for k in range(1, n)],
            }
            pub({"type": "offer", "seat": seat, "give": action["give"], "want": action["want"]})
            record({"type": "offer", "seat": seat, "give": action["give"],
                    "want": action["want"]})
            frame("offer", seat=seat, give=action["give"], want=action["want"])
            state = "trade"
        elif kind == "bank_trade":
            pay_cost(hands[seat], action["give"])
            for resource, amount in action["want"].items():
                hands[seat][resource] += amount
            pub({"type": "bank_trade", "seat": seat, "give": action["give"],
                 "want": action["want"]})
            record({"type": "bank_trade", "seat": seat, "give": action["give"],
                    "want": action["want"]})
            frame("bank_trade", seat=seat, give=action["give"], want=action["want"])

    # -- main loop ---------------------------------------------------------------

    while winner_seats is None:
        if decision_number >= decision_cap:
            terminal = "cap"
            break
        if state == "setup_settlement":
            seat = setup_order[setup_pointer]
            fallback = first_settlement_spot()
            if fallback is None:  # unreachable at setup scale, but stay finite
                advance_setup()
                continue
            action, _ = decide(
                seat, {"type": "setup_settlement", "round": setup_round},
                {"type": "build_settlement", "vertex": fallback},
                validate_setup_settlement,
            )
            place_settlement(seat, action["vertex"], free=True)
            last_setup_vertex = action["vertex"]
            state = "setup_road"
        elif state == "setup_road":
            seat = setup_order[setup_pointer]
            fallback = first_setup_road()
            if fallback is None:
                advance_setup()
                continue
            action, _ = decide(
                seat, {"type": "setup_road", "round": setup_round},
                {"type": "build_road", "edge": fallback},
                validate_setup_road,
            )
            place_road(seat, action["edge"], free=True)
            if setup_round == 2:
                setup_production(seat, last_setup_vertex)
            advance_setup()
        elif state == "robber":
            seat = active
            hex_fallback = first_robber_hex()
            targets = steal_targets(hex_fallback, seat)
            action, _ = decide(
                seat, {"type": "robber"},
                {"type": "move_robber", "hex": hex_fallback,
                 "steal": targets[0] if targets else None},
                validate_robber,
            )
            apply_robber(seat, action["hex"], action["steal"])
            state = "main"
        elif state == "free_road":
            seat = active
            fallback = first_road(seat)
            if fallback is None:
                free_roads = 0
                state = "main"
                continue
            action, _ = decide(
                seat, {"type": "free_road", "remaining": free_roads},
                {"type": "build_road", "edge": fallback},
                validate_free_road,
            )
            place_road(seat, action["edge"], free=True)
            free_roads -= 1
            state = "main" if free_roads <= 0 else "free_road"
        elif state == "trade":
            run_trade_step()
        else:  # state == "main"
            run_main_step()

    if terminal == "cap":
        final_vp = [vp[seat] + dev_hands[seat]["vp"] for seat in range(n)]
        best = max(final_vp)
        winner_seats = [seat for seat in range(n) if final_vp[seat] == best]
    points = [vp[seat] + dev_hands[seat]["vp"] for seat in range(n)]
    share = 1.0 / len(winner_seats)
    match_points = [share if seat in winner_seats else 0.0 for seat in range(n)]
    frame("end", reason=terminal, winner_seats=winner_seats, points=points)
    log.append({
        "type": "end", "reason": terminal, "winner_seats": winner_seats,
        "points": points, "hands": [dict(hand) for hand in hands],
        "dev_hands": [dict(cards) for cards in dev_hands],
        "dev_deck": list(dev_deck),
    })
    return {
        "points": points,
        "match_points": match_points,
        "winner_seats": winner_seats,
        "terminal_reason": terminal,
        "faults": faults,
        "errors": errors,
        "hands": 1,
        "matches": 1,
        "decisions": decision_number,
        "names": names,
        "log": log,
        "frames": frames,
        "replay": {"game": GAME_ID, "protocol": PROTOCOL, "names": names, "frames": frames},
    }
