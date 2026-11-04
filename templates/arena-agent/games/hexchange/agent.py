"""A small, readable Hexchange starter. No network or model calls during gameplay.

Hexchange protocol 1 observations you receive (see RULES.md / GAMES_CONTRACT.md §12):
  board      19 hexes (terrain + number tokens), 54 vertices, 72 edges — ids are
             stable integers; the seed never moves them
  robber     hex id currently blocked by the robber
  buildings  every settlement/city: {"seat", "vertex", "kind"}
  roads      every road: {"seat", "edge"}
  players    seat/name/resource-count/public-VP per seat — never identities!
  resources  YOUR resource tokens by type: {"brick": n, "forest": n, ...}
  dev_cards  YOUR development cards by type (opponents' are hidden entirely)
  turn       what the engine wants from you right now:
               setup_settlement | setup_road        free placement during setup
               robber                              {"type": "move_robber", ...}
               main                                build / buy / play / offer /
                                                   bank_trade / end_turn
               respond                             accept | reject | counter
               free_road                           a road-building payout
  history    the last 100 public events (rolls, builds, offers, responses, ...)

Return one of (per turn type):
  {"type": "build_settlement", "vertex": v}   setup, or main when you pay the cost
  {"type": "build_road", "edge": e}           setup, main, or free_road
  {"type": "build_city", "vertex": v}         upgrade your own settlement
  {"type": "buy_dev"}                         draw a hidden development card
  {"type": "play_dev", "card": ..., ...}      knight / monopoly / road_building /
                                              year_of_plenty (never the just-bought one)
  {"type": "offer", "give": {...}, "want": {...}}   open a trade (max 3 per turn)
  {"type": "bank_trade", "give": {"brick": 4}, "want": {"wheat": 1}}  flat 4:1
  {"type": "accept" | "reject"}               answer an offer
  {"type": "counter", "give": {...}, "want": {...}}
  {"type": "end_turn"}                        finish your main phase

Invalid actions are recorded as faults and replaced with a deterministic
fallback (end your turn, or reject the offer), so always answer something legal.
"""

SETTLEMENT_COST = {"brick": 1, "forest": 1, "pasture": 1, "wheat": 1}
CITY_COST = {"wheat": 2, "ore": 3}
ROAD_COST = {"brick": 1, "forest": 1}
DEV_COST = {"ore": 1, "pasture": 1, "wheat": 1}
RESOURCES = ("brick", "forest", "ore", "pasture", "wheat")
PIPS = {2: 1, 3: 2, 4: 3, 5: 4, 6: 5, 8: 5, 9: 4, 10: 3, 11: 2, 12: 1}


def can_afford(hand, cost):
    return all(hand.get(resource, 0) >= amount for resource, amount in cost.items())


def pip_total(observation, vertex):
    """Production value of a vertex: pip weights of adjacent, unblocked hexes."""
    total = 0
    for hex_id in observation["board"]["vertices"][vertex]["hexes"]:
        hex_entry = observation["board"]["hexes"][hex_id]
        if hex_id != observation["robber"] and hex_entry["number"] is not None:
            total += PIPS.get(hex_entry["number"], 0)
    return total


def settlement_spots(observation):
    """Empty vertices at distance >= 2 from every building."""
    buildings = {b["vertex"] for b in observation["buildings"]}
    return [
        v["id"] for v in observation["board"]["vertices"]
        if v["id"] not in buildings
        and all(u not in buildings for u in v["vertices"])
    ]


def connected_spots(observation, seat):
    """Settlement spots that also touch one of the seat's roads."""
    roads = {r["edge"]: r["seat"] for r in observation["roads"]}
    return [
        vertex for vertex in settlement_spots(observation)
        if any(roads.get(e) == seat
               for e in observation["board"]["vertices"][vertex]["edges"])
    ]


def road_edges(observation, seat):
    """Empty edges that legally connect to the seat's network."""
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


def best_spot(observation, spots):
    return max(spots, key=lambda v: (pip_total(observation, v), -v))


def best_road(observation, edges):
    spots = set(settlement_spots(observation))

    def value(edge):
        ends = observation["board"]["edges"][edge]["vertices"]
        return max((pip_total(observation, v) for v in ends if v in spots), default=-1)

    return max(edges, key=lambda e: (value(e), -e))


def my_pieces(observation, seat):
    mine = {"road": 0, "settlement": 0, "city": 0}
    for road in observation["roads"]:
        if road["seat"] == seat:
            mine["road"] += 1
    for building in observation["buildings"]:
        if building["seat"] == seat:
            mine[building["kind"]] += 1
    return mine


def move_robber(observation, seat):
    """Block the best opponent hex and steal from the richest adjacent victim."""
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


class Agent:
    def __init__(self):
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

    def act(self, observation: dict) -> dict:
        self._track(observation["history"])
        turn = observation["turn"]
        seat = observation["seat"]
        hand = observation["resources"]
        kind = turn["type"]

        if kind == "setup_settlement":
            return {"type": "build_settlement",
                    "vertex": best_spot(observation, settlement_spots(observation))}
        if kind == "setup_road":
            # The road must touch the settlement this seat just placed.
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
            return move_robber(observation, seat)
        if kind == "free_road":
            return {"type": "build_road",
                    "edge": best_road(observation, road_edges(observation, seat))}
        if kind == "respond":
            offer = turn["offer"]
            # Take small affordable deals; otherwise let the offer pass.
            if can_afford(hand, offer["want"]) and sum(offer["want"].values()) <= 2:
                return {"type": "accept"}
            return {"type": "reject"}

        # Main phase: build first, then improve, then trade with the bank.
        pieces = my_pieces(observation, seat)
        table_roads = len(observation["roads"])
        if (can_afford(hand, SETTLEMENT_COST) and pieces["settlement"] < 5):
            spots = connected_spots(observation, seat)
            if spots:
                return {"type": "build_settlement", "vertex": best_spot(observation, spots)}
        if can_afford(hand, ROAD_COST) and pieces["road"] < 15 and table_roads < 54:
            edges = road_edges(observation, seat)
            if edges:
                return {"type": "build_road", "edge": best_road(observation, edges)}
        if can_afford(hand, CITY_COST) and pieces["city"] < 4:
            own = [b["vertex"] for b in observation["buildings"]
                   if b["seat"] == seat and b["kind"] == "settlement"]
            if own:
                return {"type": "build_city", "vertex": best_spot(observation, own)}
        if can_afford(hand, DEV_COST) and self._buys_seen < 25:
            return {"type": "buy_dev"}
        # One card short of a settlement? Convert surplus at the bank's 4:1 desk.
        missing = [r for r in RESOURCES if hand[r] < SETTLEMENT_COST.get(r, 0)]
        if missing:
            want_type = min(missing, key=lambda r: (hand[r], RESOURCES.index(r)))
            rich = [r for r in RESOURCES if hand[r] >= 4 and r != want_type]
            if rich:
                give_type = max(rich, key=lambda r: (hand[r], -RESOURCES.index(r)))
                return {"type": "bank_trade",
                        "give": {give_type: 4}, "want": {want_type: 1}}
        return {"type": "end_turn"}
