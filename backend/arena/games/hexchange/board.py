"""Hexchange island: board graph, number tokens, and resource tokens.

Hexchange v1 owns its resource tokens outright (the contract forbids
``games/common/deck.py`` here): resources are opaque per-seat string tokens
counted by type, produced by island terrain, and paid from plain integer
hands. Nothing here touches the global ``random`` module — every shuffle
flows from the caller's ``random.Random``, so a match replays from its seed.

The island is the classic 19-hex graph — pointy-top hexes in rows of
3-4-5-4-3, 54 buildable vertices and 72 road edges. Hex, vertex, and edge ids
are fixed by geometry and never depend on the seed; the seed only shuffles
terrain and number tokens onto the hexes.
"""
from __future__ import annotations

import math
import random

FOREST = "forest"
PASTURE = "pasture"
WHEAT = "wheat"
BRICK = "brick"
ORE = "ore"
DESERT = "desert"

# Terrain and its resource token share a name (RULES.md §2).
RESOURCE_TYPES = ("brick", "forest", "ore", "pasture", "wheat")

HEX_TERRAINS: dict[str, int] = {FOREST: 4, PASTURE: 4, WHEAT: 4, BRICK: 3, ORE: 3, DESERT: 1}
NUMBER_TOKENS = (2, 3, 3, 4, 4, 5, 5, 6, 6, 8, 8, 9, 9, 10, 10, 11, 11, 12)
PIPS = {2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 8: 5, 9: 4, 10: 3, 11: 2, 12: 1}

# Cost matrix frozen in RULES.md §7 and GAMES_CONTRACT.md §12.
COSTS = {
    "road": {BRICK: 1, FOREST: 1},
    "settlement": {BRICK: 1, FOREST: 1, PASTURE: 1, WHEAT: 1},
    "city": {WHEAT: 2, ORE: 3},
    "dev": {ORE: 1, PASTURE: 1, WHEAT: 1},
}

# Shared table supply plus the classic per-seat piece limits (RULES.md §7).
ROAD_SUPPLY = 54
SETTLEMENT_SUPPLY = 20
CITY_SUPPLY = 16
PER_SEAT_ROADS = 15
PER_SEAT_SETTLEMENTS = 5
PER_SEAT_CITIES = 4

_ISLAND_RADIUS = 2   # rows of 3-4-5-4-3 hexes
_CORNER_ROUND = 4    # vertex dedupe precision (distinct vertices are >= 0.5 apart)

_AXIAL_NEIGHBORS = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))


def _island_axials() -> list[tuple[int, int]]:
    """The 19 axial coordinates of the island, in stable row order."""
    cells = []
    for r in range(-_ISLAND_RADIUS, _ISLAND_RADIUS + 1):
        for q in range(max(-_ISLAND_RADIUS, -_ISLAND_RADIUS - r),
                       min(_ISLAND_RADIUS, _ISLAND_RADIUS - r) + 1):
            cells.append((q, r))
    return cells


def _corner_position(q: int, r: int, corner: int) -> tuple[float, float]:
    """Pointy-top corner `corner` (0..5) of the hex at axial (q, r)."""
    cx = math.sqrt(3.0) * (q + r / 2.0)
    cy = 1.5 * r
    angle = math.radians(60.0 * corner - 30.0)
    return cx + math.cos(angle), cy + math.sin(angle)


class HexBoard:
    """The seeded island as plain graph records (all JSON-serializable views)."""

    def __init__(self, hexes: list[dict], vertices: list[dict], edges: list[dict]):
        self.hexes = hexes
        self.vertices = vertices
        self.edges = edges
        self.desert_hex = next(h["id"] for h in hexes if h["terrain"] == DESERT)

    def hex_vertices(self, hex_id: int) -> list[int]:
        return self.hexes[hex_id]["vertices"]

    def hex_edges(self, hex_id: int) -> list[int]:
        return self.hexes[hex_id]["edges"]

    def hex_neighbors(self, hex_id: int) -> list[int]:
        return self.hexes[hex_id]["neighbors"]

    def vertex_hexes(self, vertex_id: int) -> list[int]:
        return self.vertices[vertex_id]["hexes"]

    def vertex_edges(self, vertex_id: int) -> list[int]:
        return self.vertices[vertex_id]["edges"]

    def adjacent_vertices(self, vertex_id: int) -> list[int]:
        return self.vertices[vertex_id]["vertices"]

    def edge_vertices(self, edge_id: int) -> list[int]:
        return self.edges[edge_id]["vertices"]


def build_board(rng: random.Random) -> HexBoard:
    """Generate the island: fixed geometry, seeded terrain and number tokens.

    Consumes exactly two shuffles from ``rng`` (terrain, then number tokens)
    so the surrounding match keeps one deterministic random stream.
    """
    axials = _island_axials()
    terrains = [terrain for terrain, count in HEX_TERRAINS.items() for _ in range(count)]
    rng.shuffle(terrains)
    tokens = list(NUMBER_TOKENS)
    rng.shuffle(tokens)

    corner_keys: list[list[tuple[float, float]]] = []
    for q, r in axials:
        corner_keys.append([
            (round(x, _CORNER_ROUND), round(y, _CORNER_ROUND))
            for x, y in (_corner_position(q, r, corner) for corner in range(6))
        ])
    unique_keys = sorted({key for corners in corner_keys for key in corners})
    vertex_ids = {key: index for index, key in enumerate(unique_keys)}

    edge_pairs = set()
    for corners in corner_keys:
        for corner in range(6):
            a = vertex_ids[corners[corner]]
            b = vertex_ids[corners[(corner + 1) % 6]]
            edge_pairs.add((min(a, b), max(a, b)))
    edge_list = sorted(edge_pairs)
    edge_ids = {pair: index for index, pair in enumerate(edge_list)}

    axial_index = {axial: index for index, axial in enumerate(axials)}
    hexes: list[dict] = []
    token_index = 0
    for index, (q, r) in enumerate(axials):
        terrain = terrains[index]
        number = None
        if terrain != DESERT:
            number = tokens[token_index]
            token_index += 1
        vertices = [vertex_ids[key] for key in corner_keys[index]]
        edges = []
        for corner in range(6):
            a, b = vertices[corner], vertices[(corner + 1) % 6]
            edges.append(edge_ids[(min(a, b), max(a, b))])
        neighbors = [
            axial_index[(q + dq, r + dr)]
            for dq, dr in _AXIAL_NEIGHBORS
            if (q + dq, r + dr) in axial_index
        ]
        hexes.append({
            "id": index, "q": q, "r": r, "terrain": terrain, "number": number,
            "vertices": vertices, "edges": edges, "neighbors": sorted(neighbors),
        })

    vertices: list[dict] = [
        {"id": index, "hexes": [], "edges": [], "vertices": set()}
        for index in range(len(unique_keys))
    ]
    for entry in hexes:
        for vertex in entry["vertices"]:
            vertices[vertex]["hexes"].append(entry["id"])
    for edge, (a, b) in enumerate(edge_list):
        vertices[a]["edges"].append(edge)
        vertices[b]["edges"].append(edge)
        vertices[a]["vertices"].add(b)
        vertices[b]["vertices"].add(a)
    for entry in vertices:
        entry["vertices"] = sorted(entry["vertices"])
        entry["hexes"].sort()
        entry["edges"].sort()

    edges: list[dict] = []
    for edge, (a, b) in enumerate(edge_list):
        touching = sorted(
            entry["id"] for entry in hexes if edge in entry["edges"]
        )
        edges.append({"id": edge, "vertices": [a, b], "hexes": touching})

    return HexBoard(hexes, vertices, edges)


def board_view(board: HexBoard) -> dict:
    """The static public board structure embedded in every observation."""
    return {
        "hexes": [
            {"id": h["id"], "q": h["q"], "r": h["r"], "terrain": h["terrain"],
             "number": h["number"], "vertices": list(h["vertices"]),
             "edges": list(h["edges"]), "neighbors": list(h["neighbors"])}
            for h in board.hexes
        ],
        "vertices": [
            {"id": v["id"], "hexes": list(v["hexes"]), "edges": list(v["edges"]),
             "vertices": list(v["vertices"])}
            for v in board.vertices
        ],
        "edges": [
            {"id": e["id"], "vertices": list(e["vertices"])} for e in board.edges
        ],
    }


# -- resource tokens (own module; never games/common/deck.py) -----------------


def empty_hand() -> dict[str, int]:
    """A fresh zeroed hand: resource type -> token count."""
    return {resource: 0 for resource in RESOURCE_TYPES}


def hand_total(hand: dict[str, int]) -> int:
    return sum(hand.values())


def can_afford(hand: dict[str, int], cost: dict[str, int]) -> bool:
    return all(hand.get(resource, 0) >= amount for resource, amount in cost.items())


def pay_cost(hand: dict[str, int], cost: dict[str, int]) -> None:
    for resource, amount in cost.items():
        hand[resource] -= amount


def move_resources(source: dict[str, int], target: dict[str, int],
                   mapping: dict[str, int]) -> None:
    """Move exact token counts between hands; the caller guarantees payment."""
    for resource, amount in mapping.items():
        source[resource] -= amount
        target[resource] += amount


def valid_resource_map(raw) -> dict[str, int] | None:
    """Normalize a trade side to {resource: positive int}; None if malformed."""
    if type(raw) is not dict or not raw:
        return None
    normalized: dict[str, int] = {}
    for resource, amount in raw.items():
        if type(resource) is not str or resource not in RESOURCE_TYPES:
            return None
        if type(amount) is not int or amount <= 0:
            return None
        normalized[resource] = amount
    return normalized
