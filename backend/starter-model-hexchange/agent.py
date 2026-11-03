"""Example NumPy model agent for Stack Theory Hexchange v1.

A tiny linear scorer over hand-crafted public features, driven by weights.json
so you can replace the numbers without touching code. Uses only NumPy and the
observation it receives — never hidden state. Training happens on your
machine; only this inference artifact is submitted.
"""
import json
from pathlib import Path

import numpy as np

SETTLEMENT_COST = {"brick": 1, "forest": 1, "pasture": 1, "wheat": 1}
CITY_COST = {"wheat": 2, "ore": 3}
ROAD_COST = {"brick": 1, "forest": 1}
DEV_COST = {"ore": 1, "pasture": 1, "wheat": 1}
RESOURCES = ("brick", "forest", "ore", "pasture", "wheat")
PIPS = {2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 8: 5, 9: 4, 10: 3, 11: 2, 12: 1}


def can_afford(hand, cost):
    return all(hand.get(resource, 0) >= amount for resource, amount in cost.items())


def pip_total(observation, vertex):
    total = 0
    for hex_id in observation["board"]["vertices"][vertex]["hexes"]:
        hex_entry = observation["board"]["hexes"][hex_id]
        if hex_id != observation["robber"] and hex_entry["number"] is not None:
            total += PIPS.get(hex_entry["number"], 0)
    return total


def settlement_spots(observation):
    buildings = {b["vertex"] for b in observation["buildings"]}
    return [
        v["id"] for v in observation["board"]["vertices"]
        if v["id"] not in buildings
        and all(u not in buildings for u in v["vertices"])
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


class Agent:
    def __init__(self):
        self.weights = json.loads(Path(__file__).with_name("weights.json").read_text())
        self._window = None
        self._buys_seen = 0

    def reset(self):
        """Fresh match; forget the observed event stream."""
        self._window = None
        self._buys_seen = 0

    def _track(self, history):
        """Count every public dev purchase ever seen, across the sliding window.

        Observations carry only the last 100 events; aligning the new window
        against the previous one recovers exactly the newly appended events, so
        the hidden deck's remaining size stays derivable all match long.
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
        self._window = history

    def _deck_remaining(self):
        return 25 - self._buys_seen

    def _score(self, name, features):
        vector = np.asarray(self.weights[f"{name}_w"], dtype=float)
        return float(vector @ np.asarray(features, dtype=float) + self.weights[f"{name}_b"])

    def act(self, observation: dict) -> dict:
        self._track(observation["history"])
        turn = observation["turn"]
        seat = observation["seat"]
        kind = turn["type"]
        if kind == "setup_settlement":
            spots = settlement_spots(observation)
            return {"type": "build_settlement", "vertex": self._best(observation, spots)}
        if kind == "setup_road":
            vertex = None
            for event in observation["history"]:
                if (event.get("type") == "build" and event.get("built") == "settlement"
                        and event.get("seat") == seat):
                    vertex = event["id"]
            roads = {r["edge"] for r in observation["roads"]}
            edges = [e for e in observation["board"]["vertices"][vertex]["edges"]
                     if e not in roads]
            return {"type": "build_road", "edge": min(edges)}
        if kind == "robber":
            return self._robber(observation, seat)
        if kind == "free_road":
            edges = road_edges(observation, seat)
            return {"type": "build_road", "edge": self._best_edge(observation, edges)}
        if kind == "respond":
            return self._respond(observation)
        return self._main(observation, seat)

    def _best(self, observation, spots):
        return max(spots, key=lambda v: (pip_total(observation, v), -v))

    def _best_edge(self, observation, edges):
        spots = set(settlement_spots(observation))

        def value(edge):
            ends = observation["board"]["edges"][edge]["vertices"]
            return max((pip_total(observation, v) for v in ends if v in spots), default=-1)

        return max(edges, key=lambda e: (value(e), -e))

    def _robber(self, observation, seat):
        buildings = {b["vertex"]: (b["seat"], b["kind"]) for b in observation["buildings"]}
        best_hex, best_score = None, None
        for entry in observation["board"]["hexes"]:
            if entry["id"] == observation["robber"]:
                continue
            score = 0
            for vertex in entry["vertices"]:
                occupant = buildings.get(vertex)
                if occupant is not None and occupant[0] != seat:
                    score += 2 if occupant[1] == "city" else 1
            if best_score is None or score > best_score:
                best_hex, best_score = entry["id"], score
        counts = {p["seat"]: p["count"] for p in observation["players"]}
        targets = []
        for vertex in observation["board"]["hexes"][best_hex]["vertices"]:
            occupant = buildings.get(vertex)
            if (occupant is not None and occupant[0] != seat
                    and counts[occupant[0]] > 7 and occupant[0] not in targets):
                targets.append(occupant[0])
        steal = max(targets, key=lambda s: (counts[s], -s)) if targets else None
        return {"type": "move_robber", "hex": best_hex, "steal": steal}

    def _respond(self, observation):
        offer = observation["turn"]["offer"]
        hand = observation["resources"]
        missing = sum(1 for r, need in offer["want"].items() if hand[r] < need)
        features = [
            1.0 if can_afford(hand, offer["want"]) else 0.0,
            float(sum(offer["want"].values())),
            float(len(offer["give"]) - missing),
        ]
        if self._score("accept", features) >= 0.0:
            return {"type": "accept"}
        return {"type": "reject"}

    def _main(self, observation, seat):
        hand = observation["resources"]
        own_settlements = [b["vertex"] for b in observation["buildings"]
                           if b["seat"] == seat and b["kind"] == "settlement"]
        own_cities = sum(1 for b in observation["buildings"]
                         if b["seat"] == seat and b["kind"] == "city")
        own_roads = sum(1 for r in observation["roads"] if r["seat"] == seat)
        spots = settlement_spots(observation)
        roads = {r["edge"]: r["seat"] for r in observation["roads"]}
        connected = [
            v for v in spots
            if any(roads.get(e) == seat
                   for e in observation["board"]["vertices"][v]["edges"])
        ]
        edges = road_edges(observation, seat)
        goals = {
            "settlement": [
                1.0 if can_afford(hand, SETTLEMENT_COST) and len(connected)
                and len(own_settlements) < 5 else 0.0,
                float(min(len(connected), 3)),
                float(max((pip_total(observation, v) for v in connected), default=0)) / 15.0,
            ],
            "road": [
                1.0 if can_afford(hand, ROAD_COST) and edges
                and own_roads < 15 and len(observation["roads"]) < 54 else 0.0,
                float(min(len(edges), 5)),
                float(min(len(connected), 3)),
            ],
            "city": [
                1.0 if can_afford(hand, CITY_COST) and own_settlements
                and own_cities < 4 else 0.0,
                float(len(own_settlements)),
                float(max((pip_total(observation, v) for v in own_settlements), default=0)) / 15.0,
            ],
            "dev": [
                1.0 if can_afford(hand, DEV_COST) and self._deck_remaining() > 0 else 0.0,
                float(observation["dev_cards"]["knight"]),
                float(min(hand["ore"] + hand["wheat"], 6)),
            ],
        }
        for name in ("settlement", "road", "city", "dev"):
            if goals[name][0] == 0.0:
                continue
            if name == "settlement" and not connected:
                continue
            if name == "road" and not edges:
                continue
            if name == "city" and not own_settlements:
                continue
            return self._execute(name, observation, seat, connected, edges, own_settlements)
        # Nothing affordable: trade toward a settlement at the bank's 4:1 desk.
        missing = [r for r in RESOURCES if hand[r] < SETTLEMENT_COST.get(r, 0)]
        if missing:
            want_type = min(missing, key=lambda r: (hand[r], RESOURCES.index(r)))
            rich = [r for r in RESOURCES if hand[r] >= self.weights["bank_give"]
                    and r != want_type]
            if rich:
                give_type = max(rich, key=lambda r: (hand[r], -RESOURCES.index(r)))
                return {"type": "bank_trade",
                        "give": {give_type: self.weights["bank_give"]},
                        "want": {want_type: 1}}
        return {"type": "end_turn"}

    def _execute(self, name, observation, seat, spots, edges, own_settlements):
        if name == "settlement":
            return {"type": "build_settlement", "vertex": self._best(observation, spots)}
        if name == "road":
            return {"type": "build_road", "edge": self._best_edge(observation, edges)}
        if name == "city":
            return {"type": "build_city", "vertex": self._best(observation, own_settlements)}
        return {"type": "buy_dev"}
