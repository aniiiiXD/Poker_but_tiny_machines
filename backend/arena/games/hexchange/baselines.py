"""Deterministic Hexchange baseline strategies.

Every baseline reads only the observation it is handed — never hidden state —
and derives any randomness from a seed fixed at construction, so a match is
replayable from (bots, seed) alone. The three families are deliberately
different personalities: an expander that builds first, a trader that lives on
the offer/counter overlay, and a robber-hater that buys and plays knights
early.
"""
from __future__ import annotations

import random

from .board import COSTS, PIPS, RESOURCE_TYPES, can_afford, hand_total
from .engine import (
    CITY_SUPPLY,
    DEV_DECK,
    MAX_OFFERS,
    PER_SEAT_CITIES,
    PER_SEAT_ROADS,
    PER_SEAT_SETTLEMENTS,
    ROAD_SUPPLY,
    SETTLEMENT_SUPPLY,
    STEAL_THRESHOLD,
)

DEV_COST = COSTS["dev"]
SETTLEMENT_COST = COSTS["settlement"]


class HexchangeBaseline:
    engine_hint = "hexchange"

    def __init__(self, name: str, seed: int):
        self.name = name
        self._seed = seed

    def reset(self) -> None:
        self._rng = random.Random(f"{self._seed}:{self.name}")
        self._bought_this_turn = False
        self._played_this_turn = False
        self._window = None
        self._buys_seen = 0

    def act(self, observation: dict) -> dict:
        self._track_events(observation["history"])
        return self._decide(observation)

    def _decide(self, observation: dict) -> dict:  # pragma: no cover - overridden
        raise NotImplementedError

    def _track_events(self, history: list[dict]) -> None:
        """Remember every public event ever seen, across the sliding window.

        Observations carry only the last 100 events, so a baseline keeps its
        own running alignment: the events of the new window that extend the
        previous one are counted once. Development purchases stay public
        events, so the dev deck's remaining size is derivable forever.
        """
        prev = self._window
        if prev is None:
            fresh = history
        else:
            n_prev = len(prev)
            matched = 0
            for shift in range(n_prev + 1):
                if prev[shift:] == history[:n_prev - shift]:
                    matched = n_prev - shift
                    break
            fresh = history[matched:]
        self._buys_seen += sum(1 for event in fresh if event.get("type") == "dev_bought")
        self._window = history  # already a private deep copy made by the engine

    def _deck_remaining(self) -> int:
        return len(DEV_DECK) - self._buys_seen

    # -- shared helpers ---------------------------------------------------

    @staticmethod
    def _pip_total(observation, vertex: int) -> int:
        total = 0
        for hex_id in observation["board"]["vertices"][vertex]["hexes"]:
            hex_entry = observation["board"]["hexes"][hex_id]
            if hex_id != observation["robber"] and hex_entry["number"] is not None:
                total += PIPS.get(hex_entry["number"], 0)
        return total

    def _best_spot(self, observation, spots: list[int]) -> int:
        return max(spots, key=lambda v: (self._pip_total(observation, v), -v))

    @staticmethod
    def _buildings(observation) -> dict[int, tuple[int, str]]:
        return {b["vertex"]: (b["seat"], b["kind"]) for b in observation["buildings"]}

    @staticmethod
    def _roads(observation) -> dict[int, int]:
        return {r["edge"]: r["seat"] for r in observation["roads"]}

    def _distance_spots(self, observation) -> list[int]:
        """Empty vertices at distance >= 2 from every building."""
        buildings = {b["vertex"] for b in observation["buildings"]}
        return [
            v["id"] for v in observation["board"]["vertices"]
            if v["id"] not in buildings
            and all(u not in buildings for u in v["vertices"])
        ]

    def _connected_spots(self, observation, seat: int) -> list[int]:
        roads = self._roads(observation)
        return [
            vertex for vertex in self._distance_spots(observation)
            if any(roads.get(e) == seat for e in observation["board"]["vertices"][vertex]["edges"])
        ]

    def _road_edges(self, observation, seat: int) -> list[int]:
        """Empty edges that legally connect to the seat's network."""
        roads = self._roads(observation)
        buildings = self._buildings(observation)
        vertices = observation["board"]["vertices"]

        def connects(vertex: int) -> bool:
            occupant = buildings.get(vertex)
            if occupant is not None:
                return occupant[0] == seat
            return any(roads.get(e) == seat for e in vertices[vertex]["edges"])

        return [
            e["id"] for e in observation["board"]["edges"]
            if e["id"] not in roads
            and (connects(e["vertices"][0]) or connects(e["vertices"][1]))
        ]

    def _best_road(self, observation, edges: list[int]) -> int:
        spots = set(self._distance_spots(observation))

        def value(edge: int) -> int:
            ends = observation["board"]["edges"][edge]["vertices"]
            return max((self._pip_total(observation, v) for v in ends if v in spots), default=-1)

        return max(edges, key=lambda e: (value(e), -e))

    @staticmethod
    def _piece_counts(observation, seat: int) -> dict[str, int]:
        mine = {"road": 0, "settlement": 0, "city": 0}
        for road in observation["roads"]:
            if road["seat"] == seat:
                mine["road"] += 1
        for building in observation["buildings"]:
            if building["seat"] == seat:
                mine[building["kind"]] += 1
        return mine

    @staticmethod
    def _table_supply(observation) -> dict[str, int]:
        cities = sum(1 for b in observation["buildings"] if b["kind"] == "city")
        settlements = sum(1 for b in observation["buildings"] if b["kind"] == "settlement")
        return {"road": len(observation["roads"]), "settlement": settlements, "city": cities}

    def _abundant_type(self, observation, minimum: int = 1) -> str | None:
        hand = observation["resources"]
        eligible = [r for r in RESOURCE_TYPES if hand[r] >= minimum]
        if not eligible:
            return None
        return max(eligible, key=lambda r: (hand[r], -RESOURCE_TYPES.index(r)))

    def _setup_settlement(self, observation) -> dict:
        spots = self._distance_spots(observation)
        return {"type": "build_settlement", "vertex": self._best_spot(observation, spots)}

    def _setup_road(self, observation, seat: int) -> dict:
        vertex = None
        for event in observation["history"]:
            if (event.get("type") == "build" and event.get("built") == "settlement"
                    and event.get("seat") == seat):
                vertex = event["id"]
        roads = self._roads(observation)
        edges = [e for e in observation["board"]["vertices"][vertex]["edges"] if e not in roads]
        return {"type": "build_road", "edge": min(edges)}

    def _robber_action(self, observation, seat: int, leader_bias: bool) -> dict:
        buildings = self._buildings(observation)
        best_hex, best_score = None, None
        for entry in observation["board"]["hexes"]:
            hex_id = entry["id"]
            if hex_id == observation["robber"]:
                continue
            score = 0
            for vertex in entry["vertices"]:
                occupant = buildings.get(vertex)
                if occupant is not None and occupant[0] != seat:
                    weight = 2 if occupant[1] == "city" else 1
                    if leader_bias:
                        weight *= 1 + observation["players"][occupant[0]]["vp"]
                    score += weight
            if best_score is None or score > best_score:
                best_hex, best_score = hex_id, score
        counts = {p["seat"]: p["count"] for p in observation["players"]}
        targets = []
        for vertex in observation["board"]["hexes"][best_hex]["vertices"]:
            occupant = buildings.get(vertex)
            if (occupant is not None and occupant[0] != seat
                    and counts[occupant[0]] > STEAL_THRESHOLD
                    and occupant[0] not in targets):
                targets.append(occupant[0])
        steal = max(targets, key=lambda s: (counts[s], -s)) if targets else None
        return {"type": "move_robber", "hex": best_hex, "steal": steal}

    def _respond_action(self, observation, wants_to_accept) -> dict:
        offer = observation["turn"]["offer"]
        if can_afford(observation["resources"], offer["want"]) and wants_to_accept(offer):
            return {"type": "accept"}
        return {"type": "reject"}

    def _counter_action(self, observation, seat: int) -> dict | None:
        """A counter asking for the resource this seat is shortest of."""
        turn = observation["turn"]
        if turn.get("offers_used", MAX_OFFERS) >= MAX_OFFERS:
            return None
        hand = observation["resources"]
        give_type = self._abundant_type(observation, minimum=1)
        if give_type is None:
            return None
        missing = [
            r for r in RESOURCE_TYPES
            if r != give_type and hand[r] < SETTLEMENT_COST.get(r, 0)
        ]
        if not missing:
            return None
        want_type = min(missing, key=lambda r: (hand[r], RESOURCE_TYPES.index(r)))
        give = {give_type: 1}
        want = {want_type: 1}
        if not can_afford(hand, give):
            return None
        return {"type": "counter", "give": give, "want": want}

    def _end(self) -> dict:
        self._bought_this_turn = False
        self._played_this_turn = False
        return {"type": "end_turn"}


class Expander(HexchangeBaseline):
    """Build-first: settlements and roads before everything else.

    Never opens a player trade; converts surplus at the bank's 4:1 desk when
    one card short of the next building.
    """

    def _decide(self, observation):
        turn = observation["turn"]
        seat = observation["seat"]
        kind = turn["type"]
        if kind == "setup_settlement":
            return self._setup_settlement(observation)
        if kind == "setup_road":
            return self._setup_road(observation, seat)
        if kind == "robber":
            return self._robber_action(observation, seat, leader_bias=False)
        if kind == "free_road":
            return {"type": "build_road", "edge": self._best_road(
                observation, self._road_edges(observation, seat))}
        if kind == "respond":
            return self._respond_action(
                observation, lambda offer: hand_total(offer["want"]) <= 2)
        return self._main(observation, seat)

    def _main(self, observation, seat: int) -> dict:
        hand = observation["resources"]
        pieces = self._piece_counts(observation, seat)
        table = self._table_supply(observation)
        if (can_afford(hand, COSTS["settlement"])
                and pieces["settlement"] < PER_SEAT_SETTLEMENTS
                and table["settlement"] < SETTLEMENT_SUPPLY):
            spots = self._connected_spots(observation, seat)
            if spots:
                return {"type": "build_settlement", "vertex": self._best_spot(observation, spots)}
        if (can_afford(hand, COSTS["road"])
                and pieces["road"] < PER_SEAT_ROADS and table["road"] < ROAD_SUPPLY):
            edges = self._road_edges(observation, seat)
            if edges:
                return {"type": "build_road", "edge": self._best_road(observation, edges)}
        if (can_afford(hand, COSTS["city"])
                and pieces["city"] < PER_SEAT_CITIES and table["city"] < CITY_SUPPLY):
            own_settlements = [
                b["vertex"] for b in observation["buildings"]
                if b["seat"] == seat and b["kind"] == "settlement"
            ]
            if own_settlements:
                return {"type": "build_city", "vertex": self._best_spot(observation, own_settlements)}
        if can_afford(hand, COSTS["dev"]) and self._deck_remaining() > 2:
            self._bought_this_turn = True
            return {"type": "buy_dev"}
        # One card short of a settlement? Convert surplus at the bank.
        missing = [r for r in RESOURCE_TYPES if hand[r] < SETTLEMENT_COST.get(r, 0)]
        if missing:
            want_type = min(missing, key=lambda r: (hand[r], RESOURCE_TYPES.index(r)))
            give_type = self._abundant_type(observation, minimum=4)
            if give_type is not None and give_type != want_type:
                return {"type": "bank_trade", "give": {give_type: 4}, "want": {want_type: 1}}
        return self._end()


class Trader(HexchangeBaseline):
    """Lives on the overlay: opens offers when short, accepts or counters.

    Setup, robber, and building priorities mirror the expander; the trading
    desk is the difference — when it cannot afford its goal it opens a small
    structured offer instead of heading to the bank.
    """

    def _decide(self, observation):
        turn = observation["turn"]
        seat = observation["seat"]
        kind = turn["type"]
        if kind == "setup_settlement":
            return self._setup_settlement(observation)
        if kind == "setup_road":
            return self._setup_road(observation, seat)
        if kind == "robber":
            return self._robber_action(observation, seat, leader_bias=False)
        if kind == "free_road":
            return {"type": "build_road", "edge": self._best_road(
                observation, self._road_edges(observation, seat))}
        if kind == "respond":
            def wants(offer):
                return hand_total(offer["want"]) <= 2
            if can_afford(observation["resources"], turn["offer"]["want"]) and wants(turn["offer"]):
                return {"type": "accept"}
            counter = self._counter_action(observation, seat)
            return counter if counter is not None else {"type": "reject"}
        return self._main(observation, seat)

    def _main(self, observation, seat: int) -> dict:
        hand = observation["resources"]
        pieces = self._piece_counts(observation, seat)
        table = self._table_supply(observation)
        if (can_afford(hand, COSTS["settlement"])
                and pieces["settlement"] < PER_SEAT_SETTLEMENTS
                and table["settlement"] < SETTLEMENT_SUPPLY):
            spots = self._connected_spots(observation, seat)
            if spots:
                return {"type": "build_settlement", "vertex": self._best_spot(observation, spots)}
        if (can_afford(hand, COSTS["road"])
                and pieces["road"] < PER_SEAT_ROADS and table["road"] < ROAD_SUPPLY):
            edges = self._road_edges(observation, seat)
            if edges:
                return {"type": "build_road", "edge": self._best_road(observation, edges)}
        if (can_afford(hand, COSTS["city"])
                and pieces["city"] < PER_SEAT_CITIES and table["city"] < CITY_SUPPLY):
            own_settlements = [
                b["vertex"] for b in observation["buildings"]
                if b["seat"] == seat and b["kind"] == "settlement"
            ]
            if own_settlements:
                return {"type": "build_city", "vertex": self._best_spot(observation, own_settlements)}
        missing = [r for r in RESOURCE_TYPES if hand[r] < SETTLEMENT_COST.get(r, 0)]
        if missing:
            if observation["turn"].get("offers_used", 0) < MAX_OFFERS:
                give_type = self._abundant_type(observation, minimum=2)
                if give_type is not None:
                    want_type = min(missing, key=lambda r: (hand[r], RESOURCE_TYPES.index(r)))
                    if want_type != give_type:
                        return {"type": "offer",
                                "give": {give_type: 1}, "want": {want_type: 1}}
            give_type = self._abundant_type(observation, minimum=4)
            if give_type is not None:
                want_type = min(missing, key=lambda r: (hand[r], RESOURCE_TYPES.index(r)))
                if want_type != give_type:
                    return {"type": "bank_trade", "give": {give_type: 4}, "want": {want_type: 1}}
        return self._end()


class RobberHater(HexchangeBaseline):
    """Knights early: buys and plays development cards before buildings.

    Moves the robber next to the current VP leader and steals from the
    richest adjacent victim; accepts small offers that bring dev-card costs.
    """

    def _decide(self, observation):
        turn = observation["turn"]
        seat = observation["seat"]
        kind = turn["type"]
        if kind == "setup_settlement":
            return self._setup_settlement(observation)
        if kind == "setup_road":
            return self._setup_road(observation, seat)
        if kind == "robber":
            return self._robber_action(observation, seat, leader_bias=True)
        if kind == "free_road":
            return {"type": "build_road", "edge": self._best_road(
                observation, self._road_edges(observation, seat))}
        if kind == "respond":
            def wants(offer):
                return bool(set(offer["give"]) & {"ore", "pasture", "wheat"})
            return self._respond_action(observation, wants)
        return self._main(observation, seat)

    def _playable_card(self, observation) -> str | None:
        cards = observation["dev_cards"]
        if self._played_this_turn or self._bought_this_turn:
            return None
        for card in ("knight", "road_building", "year_of_plenty", "monopoly"):
            if cards[card] > 0:
                return card
        return None

    def _monopoly_type(self, observation, seat: int) -> str:
        """Rob the terrain that produces most next to everyone else."""
        buildings = self._buildings(observation)
        scores = {resource: 0 for resource in RESOURCE_TYPES}
        for entry in observation["board"]["hexes"]:
            if entry["terrain"] == "desert" or entry["id"] == observation["robber"]:
                continue
            weight = PIPS.get(entry["number"], 0)
            for vertex in entry["vertices"]:
                occupant = buildings.get(vertex)
                if occupant is not None and occupant[0] != seat:
                    scores[entry["terrain"]] += weight
        return max(RESOURCE_TYPES, key=lambda r: (scores[r], -RESOURCE_TYPES.index(r)))

    def _main(self, observation, seat: int) -> dict:
        hand = observation["resources"]
        card = self._playable_card(observation)
        if card == "knight":
            self._played_this_turn = True
            return {"type": "play_dev", "card": "knight"}
        if card == "road_building":
            self._played_this_turn = True
            return {"type": "play_dev", "card": "road_building"}
        if card == "year_of_plenty":
            self._played_this_turn = True
            picks = sorted(
                RESOURCE_TYPES, key=lambda r: (hand[r], RESOURCE_TYPES.index(r))
            )[:2]
            return {"type": "play_dev", "card": "year_of_plenty", "resources": picks}
        if card == "monopoly":
            self._played_this_turn = True
            return {"type": "play_dev", "card": "monopoly",
                    "resource": self._monopoly_type(observation, seat)}
        if can_afford(hand, COSTS["dev"]) and self._deck_remaining() > 2:
            self._bought_this_turn = True
            return {"type": "buy_dev"}
        pieces = self._piece_counts(observation, seat)
        table = self._table_supply(observation)
        if (can_afford(hand, COSTS["settlement"])
                and pieces["settlement"] < PER_SEAT_SETTLEMENTS
                and table["settlement"] < SETTLEMENT_SUPPLY):
            spots = self._connected_spots(observation, seat)
            if spots:
                return {"type": "build_settlement", "vertex": self._best_spot(observation, spots)}
        if (can_afford(hand, COSTS["road"])
                and pieces["road"] < PER_SEAT_ROADS and table["road"] < ROAD_SUPPLY):
            edges = self._road_edges(observation, seat)
            if edges:
                return {"type": "build_road", "edge": self._best_road(observation, edges)}
        if (can_afford(hand, COSTS["city"])
                and pieces["city"] < PER_SEAT_CITIES and table["city"] < CITY_SUPPLY):
            own_settlements = [
                b["vertex"] for b in observation["buildings"]
                if b["seat"] == seat and b["kind"] == "settlement"
            ]
            if own_settlements:
                return {"type": "build_city", "vertex": self._best_spot(observation, own_settlements)}
        return self._end()


FAMILIES = (Expander, Trader, RobberHater)


def make_hexchange_baselines(count: int = 3, seed: int = 0) -> list:
    if not 0 <= count <= len(FAMILIES):
        raise ValueError("Hexchange has between 0 and 3 baseline strategies.")
    names = ("Expander", "Trader", "RobberHater")
    bots = []
    for index in range(count):
        bot = FAMILIES[index](names[index], seed)
        bot.reset()
        bots.append(bot)
    return bots


def make_hexchange_table(seats: int = 4, seed: int = 0) -> list:
    """A full table of baselines for 3 or 4 seats (unique names per seat)."""
    if seats not in (3, 4):
        raise ValueError("Hexchange tables have 3 or 4 seats.")
    roster = [Expander, Trader, RobberHater, Trader]
    bots = []
    for index in range(seats):
        family = roster[index]
        name = family.__name__ if index < 3 else "Trader-2"
        bot = family(name, seed)
        bot.reset()
        bots.append(bot)
    return bots
