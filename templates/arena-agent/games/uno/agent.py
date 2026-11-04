"""A small, readable UNO starter. No network or model calls during gameplay.

UNO protocol 1 observations you receive (see RULES.md in the game package):
  hand          your cards, e.g. ["r7a", "bskipa", "wwilda"]
  discard_top   the face-up card every play must match, e.g. "g3a"
  active_color  the color in effect (the chosen color after a wild)
  direction     "cw" or "ccw"
  active_seat   the seat whose turn it is
  pending_draw  penalty cards the seat about to act owes (0 otherwise)
  players       seat/name/count/uno for every player (no hidden cards!)
  turn          one of:
    {"type": "play"}                      your normal turn
    {"type": "post_draw", "card": id}     your drawn card is playable
    {"type": "penalty", "draw": k}        you owe k penalty cards
    {"type": "uno"}                       declare UNO or decline (penalty!)
    {"type": "challenge", "player": p, "card": id, "color": c, "draw": 4}
                                          wild-draw-four challenge window

Return one of:
  {"type": "play", "card": id}                a card you own; wilds add "color"
  {"type": "draw"}                            draw one card (normal or penalty)
  {"type": "pass"}                            decline the drawn card / no challenge
  {"type": "uno"}                             declare UNO
  {"type": "challenge"}                       challenge a wild draw four

Invalid actions are recorded as faults and replaced with a deterministic
fallback (draw one, or pass), so always answer something legal.
"""


class Agent:
    def reset(self):
        """Called by the engine before every match."""

    def act(self, observation: dict) -> dict:
        turn = observation["turn"]
        kind = turn["type"]
        if kind == "penalty":
            return {"type": "draw"}
        if kind == "uno":
            # Declining costs two penalty cards here; declaring is free.
            return {"type": "uno"}
        if kind == "challenge":
            # Challenge only when the wild-four player is close to going out.
            own = observation["players"][observation["seat"]]["count"]
            return {"type": "challenge"} if own <= 2 else {"type": "pass"}
        if kind == "post_draw":
            card = turn["card"]
            action = {"type": "play", "card": card}
            if card[0] == "w":
                action["color"] = self._best_color(observation["hand"])
            return action
        # Normal turn: shed the first legal natural card, wilds only when forced.
        legal = [card for card in observation["hand"] if self._playable(card, observation)]
        naturals = [card for card in legal if card[0] != "w"]
        if naturals:
            return {"type": "play", "card": min(naturals)}
        if legal:
            return {"type": "play", "card": legal[0], "color": self._best_color(observation["hand"])}
        return {"type": "draw"}

    @staticmethod
    def _playable(card: str, observation: dict) -> bool:
        if card[0] == "w":
            return True
        return (card[0] == observation["active_color"]
                or card[1:-1] == observation["discard_top"][1:-1])

    @staticmethod
    def _best_color(hand: list) -> str:
        best, best_count = "r", -1
        for color in "rygb":
            count = sum(1 for card in hand if card[0] == color)
            if count > best_count:
                best, best_count = color, count
        return best
