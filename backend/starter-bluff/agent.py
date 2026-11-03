"""A small, readable Bluff starter. No network or model calls during gameplay.

Bluff protocol 1 observations you receive (see GAMES_CONTRACT.md):
  hand          your cards, e.g. ["Ac", "9d", "2h"]
  required_rank the rank you must claim on your play turn
  turn          {"type": "play"} or {"type": "challenge", "claimant": seat,
                 "rank": claimed rank, "count": declared count}
  pile_size     face-down cards waiting to be picked up by a lost challenge
  history       public events: plays, pass/challenge decisions, resolutions
  players       seat/name/card-count for every player (no hidden cards!)

Return one of:
  {"type": "play", "cards": ["Ac"]}          1-4 cards YOU own
  {"type": "challenge"}                      during a challenge turn
  {"type": "pass"}                           during a challenge turn

Invalid actions are recorded as faults and replaced with a deterministic
fallback (your sorted-lowest card, or pass), so always answer something legal.
"""


class Agent:
    def act(self, observation: dict) -> dict:
        turn = observation["turn"]
        hand = observation["hand"]
        if turn["type"] == "play":
            rank = observation["required_rank"]
            truthful = [card for card in hand if card[0] == rank]
            if truthful:
                # Play up to two honest cards; keep the rest for later rounds.
                return {"type": "play", "cards": truthful[:2]}
            # Nothing honest to play: bluff with the single lowest card so a
            # lost challenge costs as little as possible.
            lowest = min(hand, key=lambda card: (hand.count(card), card))
            return {"type": "play", "cards": [lowest]}
        # Challenge turn: challenge only when the claim is impossible — the
        # declared count plus our own copies of that rank exceed the four
        # copies that exist in the deck.
        rank = turn["rank"]
        own = sum(1 for card in hand if card[0] == rank)
        if turn["claimant"] != observation["seat"] and turn["count"] + own > 4:
            return {"type": "challenge"}
        return {"type": "pass"}
