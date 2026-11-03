"""Stack Theory Hexchange v2 — the catanatron-backed match worker.

The rules engine is the catanatron library (GPL-3.0; see THIRD_PARTY_NOTICES.md
and RULES.md §15): it owns the island, dice, production, building legality, the
robber, development cards, bank trades, and termination. This module is the
trusted worker around it: it projects observations per the frozen §15.2 key
set, maps our ``{"type": ...}`` vocabulary onto playable catanatron actions,
runs the trade overlay as direct frequency-deck mutations, records faults with
deterministic fallbacks, and emits the v1 result/replay shapes.

Determinism model (RULES.md §15.1): catanatron draws from Python's *global*
``random`` module, so every match runs inside a module-level ``threading.Lock``
and reseeds the global stream from the match seed. Matches serialize per
process; a match is a pure function of ``(bots, seed)``. The deck/bank
arithmetic below is integer-only and touches no RNG.

Auto-executed chance steps — the dice roll and the post-7 discard — are never
shown to bots, never counted as decisions, and never faulted. The trade
overlay (``offer``/``accept``/``reject``/``counter``, at most three offers per
turn) is ours: catanatron has no player-to-player trading, so the worker
mutates ``state.player_state`` hands directly and logs public events.
"""
from __future__ import annotations

import copy
import random
import threading

from catanatron.game import Game
from catanatron.models.actions import generate_playable_actions
from catanatron.models.board import STATIC_GRAPH
from catanatron.models.decks import RESOURCE_FREQDECK_INDEXES
from catanatron.models.enums import (
    RESOURCES,
    SETTLEMENT,
    Action,
    ActionPrompt,
    ActionType,
)
from catanatron.models.map import BASE_MAP_TEMPLATE, CatanMap
from catanatron.models.player import Color, Player
from catanatron.state import yield_resources
from catanatron.state_functions import (
    player_can_play_dev,
    player_deck_to_array,
    player_has_rolled,
    player_key,
    player_num_resource_cards,
    player_resource_freqdeck_contains,
)

from ...sandbox import SandboxDown
from .board import RESOURCE_TYPES, valid_resource_map

PROTOCOL = 1
GAME_ID = "hexchange"
RULES_VERSION = 1
SEATS = (3, 4)
DECISION_CAP = 500
VP_TARGET = 10
MAX_OFFERS = 3
STEAL_THRESHOLD = 7
HISTORY_DEPTH = 100

# v1-compatibility exports: the baselines (and starter kits) import these
# constants from the engine module; their values are unchanged in v2.
CITY_SUPPLY = 16
ROAD_SUPPLY = 54
SETTLEMENT_SUPPLY = 20
PER_SEAT_ROADS = 15
PER_SEAT_SETTLEMENTS = 5
PER_SEAT_CITIES = 4
DEV_TYPES = ("knight", "vp", "monopoly", "road_building", "year_of_plenty")
DEV_DECK = (
    ["knight"] * 14 + ["vp"] * 5 + ["monopoly"] * 2
    + ["road_building"] * 2 + ["year_of_plenty"] * 2
)

# Serializes every match: catanatron uses the global `random` module, so the
# seed + lock pair is what keeps same-seed replays exact (RULES.md §15.1).
_MATCH_LOCK = threading.Lock()

COLORS = (Color.RED, Color.BLUE, Color.ORANGE, Color.WHITE)

# catanatron resource -> our terrain token name (RULES.md §15.2).
OUR_RESOURCE = {
    "WOOD": "forest", "BRICK": "brick", "SHEEP": "pasture",
    "WHEAT": "wheat", "ORE": "ore",
}
CATAN_RESOURCE = {name: catan for catan, name in OUR_RESOURCE.items()}

# Lowest-first discard priority (RULES.md §15.3 item 2): fixed alphabetical
# order over our token names — brick, forest, ore, pasture, wheat.
_DISCARD_PRIORITY = {"BRICK": 0, "WOOD": 1, "ORE": 2, "SHEEP": 3, "WHEAT": 4}

OUR_DEV = {
    "KNIGHT": "knight", "VICTORY_POINT": "vp", "MONOPOLY": "monopoly",
    "ROAD_BUILDING": "road_building", "YEAR_OF_PLENTY": "year_of_plenty",
}
CATAN_DEV = {name: catan for catan, name in OUR_DEV.items()}

# Building kinds use the v1 vocabulary in every public surface.
OUR_KIND = {"SETTLEMENT": "settlement", "CITY": "city", "ROAD": "road"}

# Sentinels returned by the main-phase mapper for worker-side phases (not
# engine actions): an overlay offer, and a road-building play the engine
# refuses to list only because no road is placeable (played-and-forfeited,
# like v1). The arena worker is the only caller of `decide`, so these never
# reach catanatron's executor and `Game.play_tick` is not used.
_OFFER = object()
_FORCED_ROAD_BUILDING = object()


def _freqdeck_of(mapping: dict[str, int]) -> list[int]:
    """Our-name resource map -> catanatron [WOOD, BRICK, SHEEP, WHEAT, ORE]."""
    deck = [0, 0, 0, 0, 0]
    for name, amount in mapping.items():
        deck[RESOURCE_FREQDECK_INDEXES[CATAN_RESOURCE[name]]] += amount
    return deck


def _project_board(catan_map) -> tuple[dict, dict, dict, list, dict]:
    """The static public board per RULES.md §15.2 (id schemes frozen there).

    Returns (board_view, coord_to_hex, hex_to_coord, edge_tuples, edge_ids).
    """
    land = set(catan_map.land_nodes)
    edge_tuples = sorted({
        tuple(sorted(edge))
        for tile in catan_map.land_tiles.values()
        for edge in tile.edges.values()
    })
    edge_ids = {pair: index for index, pair in enumerate(edge_tuples)}
    nodes_at_edge = {index: set(pair) for index, pair in enumerate(edge_tuples)}
    tiles_at_edge: dict[tuple[int, int], set[int]] = {}
    tiles_at_node: dict[int, set[int]] = {}

    coordinates = sorted(catan_map.land_tiles)
    coord_to_hex = {coordinate: catan_map.land_tiles[coordinate].id
                    for coordinate in coordinates}
    hex_to_coord = {hex_id: coordinate for coordinate, hex_id in coord_to_hex.items()}
    ordered_hexes = sorted(catan_map.land_tiles.values(), key=lambda tile: tile.id)
    for coordinate in coordinates:
        tile = catan_map.land_tiles[coordinate]
        for pair in tile.edges.values():
            tiles_at_edge.setdefault(tuple(sorted(pair)), set()).add(tile.id)
        for node in tile.nodes.values():
            tiles_at_node.setdefault(node, set()).add(tile.id)

    neighbors_of: dict[int, set[int]] = {}
    tile_coordinate: dict[int, tuple[int, int, int]] = {}
    for coordinate in coordinates:
        tile = catan_map.land_tiles[coordinate]
        shared: set[int] = set()
        for pair in tile.edges.values():
            shared |= tiles_at_edge[tuple(sorted(pair))]
        shared.discard(tile.id)
        neighbors_of[tile.id] = shared
        tile_coordinate[tile.id] = coordinate

    board_view = {
        "hexes": [
            {
                "id": tile.id,
                "coordinate": list(tile_coordinate[tile.id]),
                "q": tile_coordinate[tile.id][0],
                "r": tile_coordinate[tile.id][2],
                "terrain": "desert" if tile.resource is None
                else OUR_RESOURCE[tile.resource],
                "number": tile.number,
                "vertices": sorted(tile.nodes.values()),
                "edges": sorted(
                    edge_ids[tuple(sorted(pair))] for pair in tile.edges.values()
                ),
                "neighbors": sorted(neighbors_of[tile.id]),
            }
            for tile in ordered_hexes
        ],
        "vertices": [
            {
                "id": node,
                "hexes": sorted(tiles_at_node.get(node, ())),
                "edges": sorted(
                    index for index, ends in nodes_at_edge.items() if node in ends
                ),
                "vertices": sorted(
                    neighbor for neighbor in STATIC_GRAPH.neighbors(node)
                    if neighbor in land
                ),
            }
            for node in sorted(land)
        ],
        "edges": [
            {"id": index, "vertices": list(pair)}
            for index, pair in enumerate(edge_tuples)
        ],
        "ports": [
            {"resource": None if resource is None else OUR_RESOURCE[resource],
             "nodes": sorted(nodes)}
            for resource, nodes in sorted(
                catan_map.port_nodes.items(),
                key=lambda item: (item[0] is not None, str(item[0]), sorted(item[1])),
            )
        ],
    }
    return board_view, coord_to_hex, hex_to_coord, edge_tuples, edge_ids


def static_board(seed: int) -> dict:
    """The frozen public board projection for a seed (tests, docs, tooling).

    Deterministic under the match lock: the island's terrain, numbers, and
    ports are exactly what ``play_hexchange_match(bots, seed)`` projects — the
    worker builds the island from the seed's fresh stream before anything else
    draws from the global RNG.
    """
    with _MATCH_LOCK:
        random.seed(seed)
        catan_map = CatanMap.from_template(BASE_MAP_TEMPLATE)
    return _project_board(catan_map)[0]


class _BotPlayer(Player):
    """catanatron wrapper around one Stack Theory bot (RULES.md §15).

    ``decide(game, playable_actions)`` projects the frozen §15.2 observation
    for this seat, asks the wrapped bot, and maps its ``{"type": ...}`` reply
    onto a playable catanatron Action — an illegal reply records one fault and
    yields the deterministic fallback. Overlay offers return the ``_OFFER``
    marker for the worker instead of an Action.
    """

    def __init__(self, bot, color: Color):
        super().__init__(color)
        self.bot = bot
        self._match = None  # bound to the running match's dispatcher

    def decide(self, game, playable_actions):
        if self._match is None:
            raise RuntimeError("no Hexchange match is driving this bot")
        return self._match(self, game, playable_actions)


def play_hexchange_match(
    bots: list,
    seed: int,
    decision_cap: int = DECISION_CAP,
    capture: bool = False,
) -> dict:
    n = len(bots)
    if n not in SEATS:
        raise ValueError("Hexchange is played with 3 or 4 seats.")
    if not 1 <= decision_cap <= 100_000:
        raise ValueError("decision_cap must be between 1 and 100000.")

    with _MATCH_LOCK:
        return _run_match(list(bots), seed, decision_cap, capture)


def _run_match(bots: list, seed: int, decision_cap: int, capture: bool) -> dict:
    n = len(bots)
    names = [str(getattr(bot, "name", f"Seat {i + 1}")) for i, bot in enumerate(bots)]
    wrappers = [_BotPlayer(bot, COLORS[i]) for i, bot in enumerate(bots)]

    # catanatron seeds and drives the global RNG for everything it does; the
    # worker performs no global-RNG draws outside this critical section. The
    # island is built first — from the seed's fresh stream — so static_board()
    # reproduces it exactly, then `Game` reseeds and shuffles seats/deck.
    random.seed(seed)
    catan_map = CatanMap.from_template(BASE_MAP_TEMPLATE)
    game = Game(wrappers, seed=seed, vps_to_win=VP_TARGET, catan_map=catan_map)
    state = game.state
    # `Game` construction shuffles seating from the global RNG; the worker
    # deterministically restores the caller's bot order so seat 0 always takes
    # the first turn (RULES.md §15.3 item 4). Every player_state value is
    # still the identical initial blueprint here, so this is a pure relabel.
    state.players = wrappers
    state.colors = tuple(wrapper.color for wrapper in wrappers)
    state.color_to_index = {color: index for index, color in enumerate(state.colors)}
    colors = state.colors
    # The option list was generated inside State.__init__ against the shuffled
    # seating; regenerate it for the restored order.
    state.playable_actions = generate_playable_actions(state)

    board_view, coord_to_hex, hex_to_coord, edge_tuples, edge_ids = \
        _project_board(state.board.map)

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
    offers_used = 0
    just_bought = {color: set() for color in colors}
    staged_offer: tuple[dict, dict] | None = None

    # -- small state readers -------------------------------------------------

    def seat_of(color: Color) -> int:
        return state.color_to_index[color]

    def key_of(color: Color) -> str:
        return player_key(state, color)

    def hand_map(color: Color) -> dict[str, int]:
        key = key_of(color)
        return {
            resource: state.player_state[f"{key}_{CATAN_RESOURCE[resource]}_IN_HAND"]
            for resource in RESOURCE_TYPES
        }

    def dev_map(color: Color) -> dict[str, int]:
        key = key_of(color)
        return {
            name: state.player_state[f"{key}_{CATAN_DEV[name]}_IN_HAND"]
            for name in DEV_TYPES
        }

    def hand_total(color: Color) -> int:
        return player_num_resource_cards(state, color)

    def dev_total(color: Color) -> int:
        return sum(dev_map(color).values())

    def counts() -> list[int]:
        return [hand_total(color) for color in colors]

    def public_vp(seat: int) -> int:
        return state.player_state[f"P{seat}_VICTORY_POINTS"]

    def actual_vp(seat: int) -> int:
        return state.player_state[f"P{seat}_ACTUAL_VICTORY_POINTS"]

    # -- event streams --------------------------------------------------------

    def pub(event: dict) -> None:
        history.append(event)

    def frame(kind: str, counts_override=None, **fields) -> None:
        if capture:
            frames.append({"kind": kind,
                           "counts": counts() if counts_override is None
                           else counts_override,
                           **fields})

    def record(event: dict) -> None:
        log.append(event)  # privileged audit: may carry hidden state

    # -- the frozen observation (RULES.md §15.2) ------------------------------

    def observation(seat: int, turn: dict) -> dict:
        players = [
            {"seat": i, "name": names[i], "count": counts()[i],
             "vp": public_vp(i), "dev_count": dev_total(colors[i])}
            for i in range(n)
        ]
        return {
            "protocol": PROTOCOL,
            "game": GAME_ID,
            "rules_version": RULES_VERSION,
            "seat": seat,
            "players": players,
            "board": copy.deepcopy(board_view),
            "robber": coord_to_hex[state.board.robber_coordinate],
            "buildings": [
                {"seat": seat_of(color), "vertex": node, "kind": OUR_KIND[kind]}
                for node, (color, kind) in sorted(state.board.buildings.items())
            ],
            "roads": [
                {"seat": seat_of(color), "edge": edge_ids[pair]}
                for pair, color in sorted(
                    (pair, color) for pair, color in state.board.roads.items()
                    if pair[0] < pair[1]
                )
            ],
            "resources": hand_map(colors[seat]),
            "dev_cards": dev_map(colors[seat]),
            "turn": copy.deepcopy(turn),
            "history": copy.deepcopy(history[-HISTORY_DEPTH:]),
            "decision_number": decision_number + 1,
            "decision_cap": decision_cap,
        }

    # -- decisions ------------------------------------------------------------

    def fault(seat: int, message: str) -> None:
        faults[seat] += 1
        if errors[seat] is None:
            errors[seat] = message

    def decide(seat: int, turn: dict, fallback, validate) -> object:
        """One bot decision; faults fall back along the deterministic rule.

        `fallback` is either a raw-action dict (routed through `validate`, the
        v1 pattern) or a zero-argument callable producing the fallback Action
        directly (used by the robber mapper).
        """
        nonlocal decision_number
        decision_number += 1
        if reset_failed[seat]:
            return fallback() if callable(fallback) else validate(fallback)
        try:
            raw = bots[seat].act(observation(seat, turn))
        except SandboxDown:
            raise
        except Exception as exc:  # noqa: BLE001 — timeout/crash/transport fault
            fault(seat, str(exc)[:200])
            return fallback() if callable(fallback) else validate(fallback)
        mapped = validate(raw if type(raw) is dict else None)
        if mapped is None:
            fault(seat, "invalid " + turn["type"] + " action")
            return fallback() if callable(fallback) else validate(fallback)
        return mapped

    def playable_of(action_type: ActionType, value=None) -> Action | None:
        for candidate in state.playable_actions:
            if candidate.action_type is action_type and (
                value is None or candidate.value == value
            ):
                return candidate
        return None

    def run(action: Action) -> Action:
        """Execute an action; engine-listed ones validate, platform-legal
        exceptions (pre-rolled dice, explicit discards, declined steals,
        off-list bank trades) bypass catanatron's membership check."""
        if action in state.playable_actions:
            return game.execute(action)
        return game.execute(action, validate_action=False)

    def regen_playable() -> None:
        """Refresh the current player's option list after overlay mutations."""
        state.playable_actions = generate_playable_actions(state)

    # -- deterministic fallbacks ----------------------------------------------

    def robber_fallback(color: Color) -> Action:
        options = [a for a in state.playable_actions
                   if a.action_type is ActionType.MOVE_ROBBER]
        best_hex = min(coord_to_hex[a.value[0]] for a in options)
        coordinate = hex_to_coord[best_hex]
        ordered = sorted(options, key=lambda a: (
            seat_of(a.value[1]) if a.value[1] is not None else n, a.value[0],
        ))
        victim = None
        for option in ordered:
            if (option.value[0] == coordinate and option.value[1] is not None
                    and hand_total(option.value[1]) > STEAL_THRESHOLD):
                victim = option.value[1]
                break
        return Action(color, ActionType.MOVE_ROBBER, (coordinate, victim, None))

    # -- build / robber event emission -----------------------------------------

    def build_event(color: Color, kind: str, node_or_edge, free: bool,
                    counts_override=None) -> None:
        seat = seat_of(color)
        pub({"type": "build", "seat": seat, "built": kind,
             "id": node_or_edge, "free": free})
        record({"type": "build", "seat": seat, "built": kind,
                "id": node_or_edge, "free": free, "hand": hand_map(color)})
        frame("build", counts_override, seat=seat, built=kind,
              id=node_or_edge, free=free)

    def setup_payout(color: Color, node: int) -> None:
        seat = seat_of(color)
        gained: dict[str, int] = {}
        for tile in state.board.map.adjacent_tiles[node]:
            if tile.resource is not None:
                name = OUR_RESOURCE[tile.resource]
                gained[name] = gained.get(name, 0) + 1
        totals = [0] * n
        totals[seat] = sum(gained.values())
        pub({"type": "production", "setup": True, "seat": seat, "gained": totals})
        record({"type": "production", "setup": True, "seat": seat,
                "gained": totals, "cards": gained})
        frame("production", setup=True, seat=seat, gained=totals)

    def run_robber_action(color: Color, action: Action) -> None:
        seat = seat_of(color)
        moved_from = coord_to_hex[state.board.robber_coordinate]
        _, victim_color, _ = action.value
        # Eligibility evidence is the pre-steal hand size (> STEAL_THRESHOLD).
        victim_count = hand_total(victim_color) if victim_color is not None else None
        finalized = run(action)
        coordinate, victim_color, stolen = finalized.value
        victim_seat = seat_of(victim_color) if victim_color is not None else None
        pub({"type": "robber", "seat": seat, "moved_from": moved_from,
             "hex": coord_to_hex[coordinate], "stole_from": victim_seat})
        record({"type": "robber", "seat": seat, "moved_from": moved_from,
                "hex": coord_to_hex[coordinate], "stole_from": victim_seat,
                "card": None if stolen is None else OUR_RESOURCE[stolen],
                "victim_count": victim_count})
        frame("robber", seat=seat, moved_from=moved_from,
              hex=coord_to_hex[coordinate], stole_from=victim_seat)

    # -- auto-executed chance steps (never bot decisions) -----------------------

    def auto_roll(seat: int) -> None:
        color = colors[seat]
        dice = [random.randint(1, 6), random.randint(1, 6)]
        number = dice[0] + dice[1]
        pub({"type": "roll", "seat": seat, "dice": dice})
        record({"type": "roll", "seat": seat, "dice": dice})
        frame("roll", seat=seat, dice=dice)
        if number == 7:
            run(Action(color, ActionType.ROLL, dice))
            return  # discard and robber prompts are handled by the loop
        payout, _ = yield_resources(state.board, state.resource_freqdeck, number)
        robber_coordinate = state.board.robber_coordinate
        produced = sorted(
            coord_to_hex[coordinate]
            for coordinate, tile in state.board.map.land_tiles.items()
            if tile.number == number and coordinate != robber_coordinate
        )
        totals = [0] * n
        cards: list[dict[str, int]] = []
        for color in colors:
            gain = payout.get(color, [0, 0, 0, 0, 0])
            totals[seat_of(color)] = sum(gain)
            cards.append({
                OUR_RESOURCE[resource]: amount
                for resource, amount in zip(RESOURCES, gain) if amount
            })
        run(Action(color, ActionType.ROLL, dice))
        pub({"type": "production", "roll": number, "hexes": produced,
             "gained": totals})
        record({"type": "production", "roll": number, "hexes": produced,
                "gained": totals, "cards": cards})
        frame("production", roll=number, hexes=produced, gained=totals)

    def auto_discard() -> None:
        color = state.current_color()
        seat = seat_of(color)
        hand = player_deck_to_array(state, color)
        hand.sort(key=lambda resource: _DISCARD_PRIORITY[resource])
        discarded = hand[: len(hand) // 2]
        run(Action(color, ActionType.DISCARD, list(discarded)))
        pub({"type": "discard", "seat": seat, "discarded": len(discarded)})
        record({"type": "discard", "seat": seat, "count": len(discarded),
                "cards": [OUR_RESOURCE[card] for card in discarded]})
        frame("discard", seat=seat, discarded=len(discarded))

    # -- prompt mappers (bot decision -> catanatron Action) ---------------------

    def map_setup_settlement(seat: int) -> Action:
        color = colors[seat]
        round_no = 1 if len(state.buildings_by_color[color][SETTLEMENT]) == 0 else 2
        turn = {"type": "setup_settlement", "round": round_no}

        def validate(raw) -> Action | None:
            if raw is None or raw.get("type") != "build_settlement":
                return None
            node = raw.get("vertex")
            if type(node) is not int:
                return None
            return playable_of(ActionType.BUILD_SETTLEMENT, node)

        spot = min(a.value for a in state.playable_actions)
        return decide(seat, turn, {"type": "build_settlement", "vertex": spot},
                      validate)

    def map_setup_road(seat: int) -> Action:
        color = colors[seat]
        round_no = 1 if len(state.buildings_by_color[color][SETTLEMENT]) <= 1 else 2
        turn = {"type": "setup_road", "round": round_no}

        def validate(raw) -> Action | None:
            if raw is None or raw.get("type") != "build_road":
                return None
            edge = raw.get("edge")
            if type(edge) is not int or not 0 <= edge < len(edge_tuples):
                return None
            return playable_of(ActionType.BUILD_ROAD, edge_tuples[edge])

        edge = min(edge_ids[a.value] for a in state.playable_actions)
        return decide(seat, turn, {"type": "build_road", "edge": edge}, validate)

    def map_robber(seat: int) -> Action:
        color = colors[seat]
        current_hex = coord_to_hex[state.board.robber_coordinate]
        turn = {"type": "robber"}

        def validate(raw) -> Action | None:
            if raw is None or raw.get("type") != "move_robber":
                return None
            hex_id = raw.get("hex")
            if type(hex_id) is not int or hex_id not in hex_to_coord \
                    or hex_id == current_hex:
                return None
            coordinate = hex_to_coord[hex_id]
            steal = raw.get("steal", None)
            if steal is None:  # declining to steal is always legal (§15.3 item 6)
                return Action(color, ActionType.MOVE_ROBBER, (coordinate, None, None))
            if type(steal) is not int or not 0 <= steal < n or steal == seat:
                return None
            victim = colors[steal]
            if hand_total(victim) <= STEAL_THRESHOLD:
                return None
            tile = state.board.map.land_tiles[coordinate]
            borders = {
                state.board.buildings[node][0]
                for node in tile.nodes.values() if node in state.board.buildings
            }
            if victim not in borders:
                return None
            return playable_of(ActionType.MOVE_ROBBER, (coordinate, victim, None))

        return decide(seat, turn, lambda: robber_fallback(color), validate)

    def map_free_road(seat: int) -> Action:
        turn = {"type": "free_road", "remaining": state.free_roads_available}

        def validate(raw) -> Action | None:
            if raw is None or raw.get("type") != "build_road":
                return None
            edge = raw.get("edge")
            if type(edge) is not int or not 0 <= edge < len(edge_tuples):
                return None
            return playable_of(ActionType.BUILD_ROAD, edge_tuples[edge])

        edge = min(edge_ids[a.value] for a in state.playable_actions)
        return decide(seat, turn, {"type": "build_road", "edge": edge}, validate)

    def map_main(seat: int) -> object:
        color = colors[seat]
        turn = {"type": "main", "offers_used": offers_used, "offers_max": MAX_OFFERS}

        def validate(raw) -> object:
            nonlocal staged_offer
            if raw is None:
                return None
            kind = raw.get("type")
            if kind == "end_turn":
                return playable_of(ActionType.END_TURN)
            if kind == "build_road":
                edge = raw.get("edge")
                if type(edge) is not int or not 0 <= edge < len(edge_tuples):
                    return None
                return playable_of(ActionType.BUILD_ROAD, edge_tuples[edge])
            if kind == "build_settlement":
                node = raw.get("vertex")
                if type(node) is not int:
                    return None
                return playable_of(ActionType.BUILD_SETTLEMENT, node)
            if kind == "build_city":
                node = raw.get("vertex")
                if type(node) is not int:
                    return None
                return playable_of(ActionType.BUILD_CITY, node)
            if kind == "buy_dev":
                return playable_of(ActionType.BUY_DEVELOPMENT_CARD)
            if kind == "play_dev":
                card = raw.get("card")
                if type(card) is not str or card not in DEV_TYPES or card == "vp":
                    return None
                catan_card = CATAN_DEV[card]
                if catan_card in just_bought[color]:
                    return None  # never the just-bought card (§15.3 item 14)
                if card == "monopoly":
                    resource = raw.get("resource")
                    if type(resource) is not str or resource not in CATAN_RESOURCE:
                        return None
                    return playable_of(ActionType.PLAY_MONOPOLY,
                                       CATAN_RESOURCE[resource])
                if card == "year_of_plenty":
                    picks = raw.get("resources")
                    if type(picks) is not list or len(picks) != 2:
                        return None
                    for pick in picks:
                        if type(pick) is not str or pick not in CATAN_RESOURCE:
                            return None
                    pair = sorted(
                        (CATAN_RESOURCE[picks[0]], CATAN_RESOURCE[picks[1]]),
                        key=RESOURCES.index,
                    )
                    exact = playable_of(ActionType.PLAY_YEAR_OF_PLENTY, tuple(pair))
                    if exact is not None:
                        return exact
                    for single in pair:  # bank-limited grant (§15.3 item 9)
                        single_action = playable_of(
                            ActionType.PLAY_YEAR_OF_PLENTY, (single,))
                        if single_action is not None:
                            return single_action
                    return None
                if card == "knight":
                    return playable_of(ActionType.PLAY_KNIGHT_CARD)
                if card == "road_building":
                    listed = playable_of(ActionType.PLAY_ROAD_BUILDING)
                    if listed is not None:
                        return listed
                    # The engine hides the card when no road is placeable; v1
                    # played it anyway and forfeited the free roads (§15.3).
                    if player_can_play_dev(state, color, "ROAD_BUILDING"):
                        return _FORCED_ROAD_BUILDING
                    return None
                return None
            if kind == "bank_trade":
                give = valid_resource_map(raw.get("give"))
                want = valid_resource_map(raw.get("want"))
                if give is None or want is None:
                    return None
                if len(give) != 1 or len(want) != 1:
                    return None
                give_resource, give_amount = next(iter(give.items()))
                want_resource, want_amount = next(iter(want.items()))
                if give_resource == want_resource or want_amount != 1:
                    return None
                if give_amount not in (2, 3, 4):
                    return None
                ports = set(state.board.get_player_port_resources(color))
                if give_amount == 3 and None not in ports:
                    return None
                if give_amount == 2 and CATAN_RESOURCE[give_resource] not in ports:
                    return None
                if not player_resource_freqdeck_contains(
                        state, color, _freqdeck_of(give)):
                    return None
                offer = (
                    (CATAN_RESOURCE[give_resource],) * give_amount
                    + (None,) * (4 - give_amount)
                    + (CATAN_RESOURCE[want_resource],)
                )
                exact = playable_of(ActionType.MARITIME_TRADE, offer)
                if exact is not None:
                    return exact
                # A worse-rate trade or an empty bank reserve: both are
                # platform-legal here (§15.3 item 7 — the bank never refuses).
                return Action(color, ActionType.MARITIME_TRADE, offer)
            if kind == "offer":
                if offers_used >= MAX_OFFERS:
                    return None
                give = valid_resource_map(raw.get("give"))
                want = valid_resource_map(raw.get("want"))
                if give is None or want is None:
                    return None
                if not player_resource_freqdeck_contains(
                        state, color, _freqdeck_of(give)):
                    return None
                staged_offer = (give, want)
                return _OFFER
            return None

        return decide(seat, turn, {"type": "end_turn"}, validate)

    # -- the trade overlay (RULES.md §15.3 item 3) ------------------------------

    def transfer(src: Color, dst: Color, mapping: dict[str, int]) -> None:
        src_key, dst_key = key_of(src), key_of(dst)
        for resource, amount in mapping.items():
            catan_resource = CATAN_RESOURCE[resource]
            state.player_state[f"{src_key}_{catan_resource}_IN_HAND"] -= amount
            state.player_state[f"{dst_key}_{catan_resource}_IN_HAND"] += amount

    def validate_respond(raw) -> dict | None:
        if raw is None or staged_trade is None:
            return None
        seat = staged_trade["queue"][0]
        color = colors[seat]
        kind = raw.get("type")
        if kind == "reject":
            return {"type": "reject"}
        if kind == "accept":
            if not player_resource_freqdeck_contains(
                    state, color, _freqdeck_of(staged_trade["want"])):
                return None
            return {"type": "accept"}
        if kind == "counter":
            if offers_used >= MAX_OFFERS:
                return None
            give = valid_resource_map(raw.get("give"))
            want = valid_resource_map(raw.get("want"))
            if give is None or want is None:
                return None
            if not player_resource_freqdeck_contains(
                    state, color, _freqdeck_of(give)):
                return None
            return {"type": "counter", "give": give, "want": want}
        return None

    staged_trade: dict | None = None

    def run_trade_overlay(author: int, give: dict, want: dict) -> str | None:
        """Negotiate the staged offer; returns "cap" if the decision cap hit."""
        nonlocal offers_used, staged_trade
        offers_used += 1
        pub({"type": "offer", "seat": author, "give": give, "want": want})
        record({"type": "offer", "seat": author, "give": give, "want": want})
        frame("offer", seat=author, give=give, want=want)
        staged_trade = {
            "author": author, "give": give, "want": want,
            "queue": [(author + k) % n for k in range(1, n)],
        }
        while staged_trade["queue"]:
            if decision_number >= decision_cap:
                return "cap"
            responder = staged_trade["queue"][0]
            turn = {
                "type": "respond",
                "offer": {"give": dict(staged_trade["give"]),
                          "want": dict(staged_trade["want"])},
                "offered_by": staged_trade["author"],
                "offers_used": offers_used,
            }
            reply = decide(responder, turn, {"type": "reject"}, validate_respond)
            kind = reply["type"]
            author_color = colors[staged_trade["author"]]
            responder_color = colors[responder]
            if kind == "accept":
                transfer(author_color, responder_color, staged_trade["give"])
                transfer(responder_color, author_color, staged_trade["want"])
                pub({"type": "accept", "seat": responder,
                     "offered_by": staged_trade["author"],
                     "give": staged_trade["give"], "want": staged_trade["want"]})
                record({"type": "accept", "seat": responder,
                        "offered_by": staged_trade["author"],
                        "give": staged_trade["give"],
                        "want": staged_trade["want"],
                        "hands_after": [hand_map(color) for color in colors]})
                frame("accept", seat=responder, offered_by=staged_trade["author"],
                      give=staged_trade["give"], want=staged_trade["want"])
                staged_trade = None
                regen_playable()
                return None
            if kind == "counter":
                offers_used += 1
                pub({"type": "counter", "seat": responder,
                     "give": reply["give"], "want": reply["want"]})
                record({"type": "counter", "seat": responder,
                        "give": reply["give"], "want": reply["want"]})
                frame("counter", seat=responder,
                      give=reply["give"], want=reply["want"])
                staged_trade = {
                    "author": responder, "give": reply["give"],
                    "want": reply["want"],
                    "queue": [(responder + k) % n for k in range(1, n)],
                }
                continue
            staged_trade["queue"].pop(0)
            pub({"type": "reject", "seat": responder})
            record({"type": "reject", "seat": responder})
            frame("reject", seat=responder)
            if not staged_trade["queue"]:
                expiring = staged_trade["author"]
                pub({"type": "trade_expired", "seat": expiring})
                record({"type": "trade_expired", "seat": expiring})
                frame("trade_expired", seat=expiring)
                staged_trade = None
                regen_playable()
                return None
        return None

    # -- main-phase execution ---------------------------------------------------

    def apply_main_action(seat: int, action: Action) -> None:
        color = colors[seat]
        mono_taken: list[int] | None = None
        if action.action_type is ActionType.PLAY_MONOPOLY:
            resource = action.value
            mono_taken = [
                state.player_state[f"{key_of(c)}_{resource}_IN_HAND"] for c in colors
            ]
        if action.action_type is ActionType.MARITIME_TRADE:
            want_resource = action.value[4]
            index = RESOURCE_FREQDECK_INDEXES[want_resource]
            if state.resource_freqdeck[index] <= 0:
                # §15.3 item 7: the bank never refuses a legitimate trade.
                state.resource_freqdeck[index] += 1
                record({"type": "bank_replenished", "seat": seat,
                        "resource": OUR_RESOURCE[want_resource]})
        finalized = run(action)
        kind = finalized.action_type
        if kind is ActionType.BUILD_SETTLEMENT:
            build_event(color, "settlement", finalized.value, free=False)
        elif kind is ActionType.BUILD_ROAD:
            build_event(color, "road", edge_ids[finalized.value], free=False)
        elif kind is ActionType.BUILD_CITY:
            build_event(color, "city", finalized.value, free=False)
        elif kind is ActionType.BUY_DEVELOPMENT_CARD:
            just_bought[color].add(finalized.value)
            pub({"type": "dev_bought", "seat": seat})
            record({"type": "dev_draw", "seat": seat,
                    "card": OUR_DEV[finalized.value],
                    "remaining": len(state.development_listdeck)})
            frame("dev_bought", seat=seat)
        elif kind is ActionType.PLAY_KNIGHT_CARD:
            pub({"type": "dev_played", "seat": seat, "card": "knight"})
            record({"type": "dev_played", "seat": seat, "card": "knight"})
            frame("dev_played", seat=seat, card="knight")
        elif kind is ActionType.PLAY_MONOPOLY:
            resource = finalized.value
            took = [0] * n
            for index, other in enumerate(colors):
                if other is not color:
                    took[index] = mono_taken[index]
            pub({"type": "dev_played", "seat": seat, "card": "monopoly",
                 "resource": OUR_RESOURCE[resource], "took": took})
            record({"type": "dev_played", "seat": seat, "card": "monopoly",
                    "resource": resource, "took": took})
            frame("dev_played", seat=seat, card="monopoly",
                  resource=OUR_RESOURCE[resource], took=took)
        elif kind is ActionType.PLAY_ROAD_BUILDING:
            pub({"type": "dev_played", "seat": seat, "card": "road_building"})
            record({"type": "dev_played", "seat": seat, "card": "road_building"})
            frame("dev_played", seat=seat, card="road_building")
        elif kind is ActionType.PLAY_YEAR_OF_PLENTY:
            granted = [OUR_RESOURCE[resource] for resource in finalized.value]
            pub({"type": "dev_played", "seat": seat, "card": "year_of_plenty",
                 "resources": granted})
            record({"type": "dev_played", "seat": seat, "card": "year_of_plenty",
                    "resources": granted})
            frame("dev_played", seat=seat, card="year_of_plenty",
                  resources=granted)
        elif kind is ActionType.MARITIME_TRADE:
            offer = finalized.value
            give: dict[str, int] = {}
            for resource in offer[:4]:
                if resource is not None:
                    name = OUR_RESOURCE[resource]
                    give[name] = give.get(name, 0) + 1
            want = {OUR_RESOURCE[offer[4]]: 1}
            pub({"type": "bank_trade", "seat": seat, "give": give, "want": want})
            record({"type": "bank_trade", "seat": seat, "give": give,
                    "want": want})
            frame("bank_trade", seat=seat, give=give, want=want)

    def run_forced_road_building(seat: int) -> None:
        color = colors[seat]
        run(Action(color, ActionType.PLAY_ROAD_BUILDING, None))
        pub({"type": "dev_played", "seat": seat, "card": "road_building"})
        record({"type": "dev_played", "seat": seat, "card": "road_building"})
        frame("dev_played", seat=seat, card="road_building")
        if not state.playable_actions:
            state.is_road_building = False
            state.free_roads_available = 0
            record({"type": "free_road_skipped", "seat": seat})
            regen_playable()

    def main_step(seat: int) -> str | None:
        color = colors[seat]
        mapped = map_main(seat)
        if mapped is _OFFER:
            give, want = staged_offer
            return run_trade_overlay(seat, give, want)
        if mapped is _FORCED_ROAD_BUILDING:
            run_forced_road_building(seat)
            return None
        if mapped.action_type is ActionType.END_TURN:
            pub({"type": "end_turn", "seat": seat})
            record({"type": "end_turn", "seat": seat, "hand": hand_map(color)})
            frame("end_turn", seat=seat)
            run(mapped)
            just_bought[color].clear()
            return None
        apply_main_action(seat, mapped)
        return None

    # -- prompt runners -----------------------------------------------------------

    def run_setup_settlement(seat: int, action: Action) -> None:
        color = colors[seat]
        free = state.is_initial_build_phase
        second = len(state.buildings_by_color[color][SETTLEMENT]) == 1
        # The engine pays the second-settlement payout inside the placement;
        # snapshot the pre-placement counts so the gain lands on the following
        # production frame (v1 frame semantics).
        before = counts() if second else None
        finalized = run(action)
        build_event(color, "settlement", finalized.value, free=free,
                    counts_override=before)
        if second:
            setup_payout(color, finalized.value)

    def run_setup_road(seat: int, action: Action) -> None:
        color = colors[seat]
        finalized = run(action)
        build_event(color, "road", edge_ids[finalized.value], free=True)

    def run_free_road(seat: int, action: Action) -> None:
        color = colors[seat]
        finalized = run(action)
        build_event(color, "road", edge_ids[finalized.value], free=True)
        if not state.playable_actions:
            state.is_road_building = False
            state.free_roads_available = 0
            regen_playable()

    # -- decide() dispatcher: routes a catanatron prompt to its mapper ----------

    def dispatch(wrapper: _BotPlayer, game: Game, playable_actions) -> object:
        prompt = state.current_prompt
        seat = seat_of(wrapper.color)
        if prompt is ActionPrompt.BUILD_INITIAL_SETTLEMENT:
            return map_setup_settlement(seat)
        if prompt is ActionPrompt.BUILD_INITIAL_ROAD:
            return map_setup_road(seat)
        if prompt is ActionPrompt.MOVE_ROBBER:
            return map_robber(seat)
        if prompt is ActionPrompt.DISCARD:
            color = wrapper.color
            hand = player_deck_to_array(state, color)
            hand.sort(key=lambda resource: _DISCARD_PRIORITY[resource])
            return Action(color, ActionType.DISCARD, list(hand[: len(hand) // 2]))
        if not player_has_rolled(state, wrapper.color):
            return Action(wrapper.color, ActionType.ROLL, None)
        if state.is_road_building:
            return map_free_road(seat)
        return map_main(seat)

    for wrapper in wrappers:
        wrapper._match = dispatch

    # -- the match loop -------------------------------------------------------------

    while True:
        leaders = [seat for seat in range(n) if actual_vp(seat) >= VP_TARGET]
        if leaders:
            winner_seats = leaders
            terminal = "win"
            break
        if decision_number >= decision_cap:
            terminal = "cap"
            break
        prompt = state.current_prompt
        if prompt is ActionPrompt.DISCARD:
            auto_discard()
            continue
        seat = seat_of(state.current_color())
        if prompt is ActionPrompt.BUILD_INITIAL_SETTLEMENT:
            run_setup_settlement(seat, map_setup_settlement(seat))
        elif prompt is ActionPrompt.BUILD_INITIAL_ROAD:
            run_setup_road(seat, map_setup_road(seat))
        elif prompt is ActionPrompt.MOVE_ROBBER:
            run_robber_action(colors[seat], map_robber(seat))
        else:  # PLAY_TURN
            if not player_has_rolled(state, state.current_color()):
                auto_roll(seat)
            elif state.is_road_building:
                if not state.playable_actions:
                    state.is_road_building = False
                    state.free_roads_available = 0
                    record({"type": "free_road_skipped", "seat": seat})
                    regen_playable()
                else:
                    run_free_road(seat, map_free_road(seat))
            else:
                if main_step(seat) == "cap":
                    continue  # the loop-top cap check terminates the match

    # -- result assembly -------------------------------------------------------------

    points = [actual_vp(seat) for seat in range(n)]
    if terminal == "cap":
        best = max(points)
        winner_seats = [seat for seat, vp in enumerate(points) if vp == best]
    share = 1.0 / len(winner_seats)
    match_points = [share if seat in winner_seats else 0.0 for seat in range(n)]
    frame("end", reason=terminal, winner_seats=winner_seats, points=points)
    log.append({
        "type": "end", "reason": terminal, "winner_seats": winner_seats,
        "points": points,
        "hands": [hand_map(color) for color in colors],
        "dev_hands": [dev_map(color) for color in colors],
        "dev_deck": [OUR_DEV[card] for card in state.development_listdeck],
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
        "replay": {"game": GAME_ID, "protocol": PROTOCOL, "names": names,
                   "frames": frames},
    }
