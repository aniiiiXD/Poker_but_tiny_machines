"""A small, readable Hearts starter. No network or model calls during gameplay.

Hearts protocol 1 observations you receive (see GAMES_CONTRACT.md §11):
  hand          your cards, e.g. ["Ac", "9d", "2h"]
  received      the 3 cards passed to you (None until the pass resolves)
  trick         plays to the current trick so far: [{"seat": 1, "card": "4c"}]
  trick_number  0 for the opening trick up to 12 for the last
  leader        seat leading the current trick
  hearts_broken True once any heart has been played to a trick
  tricks        completed tricks, fully public (winner, points, cards)
  players       seat/name/card-count/points-taken for every player
  turn          {"type": "pass"} or {"type": "play"}

Return one of:
  {"type": "pass", "cards": ["Ac", "Kd", "Qs"]}   exactly 3 cards YOU own
  {"type": "play", "card": "2c"}                  one card YOU own, legal

Invalid actions are recorded as faults and replaced with a deterministic
fallback (pass the 3 lowest; play the lowest legal card), so always answer
something legal. 2♣ opens, follow suit is mandatory, hearts cannot lead until
broken, Q♠ = 13 points, hearts = 1 each, and taking all 26 shoots the moon
(shooter 0, everyone else +26).
"""
from __future__ import annotations

QUEEN_SPADES = "Qs"
STRENGTH = {rank: index for index, rank in enumerate("23456789TJQKA")}


def low_key(card: str) -> tuple[int, int]:
    """Hearts strength order: 2 low, ace high; c < d < h < s."""
    return (STRENGTH[card[0]], "cdhs".index(card[1]))


class Agent:
    def reset(self) -> None:
        """Called once per match by the arena; keep per-match state here."""

    def act(self, observation: dict) -> dict:
        hand = observation["hand"]
        if observation["turn"]["type"] == "pass":
            # Shed the dangerous high cards; the Q♠ above all.
            danger = sorted(
                hand,
                key=lambda card: (low_key(card)[0]
                                  + (6 if card == QUEEN_SPADES else 3 if card[1] == "h" else 0),
                                  low_key(card)[1]),
                reverse=True,
            )
            return {"type": "pass", "cards": danger[:3]}
        legal = self._legal(observation)
        trick = observation["trick"]
        if not trick:
            # Lead low; never volunteer the Q♠.
            safe = [card for card in legal if card != QUEEN_SPADES] or legal
            return {"type": "play", "card": min(safe, key=low_key)}
        led_suit = trick[0]["card"][1]
        if legal[0][1] != led_suit:
            # Void: dump the Q♠, then the highest heart, then the highest card.
            if QUEEN_SPADES in legal:
                return {"type": "play", "card": QUEEN_SPADES}
            hearts = [card for card in legal if card[1] == "h"]
            return {"type": "play", "card": max(hearts or legal, key=low_key)}
        # Follow suit as high as possible without winning the trick.
        best = max((play["card"] for play in trick if play["card"][1] == led_suit), key=low_key)
        losers = [card for card in legal if low_key(card)[0] < low_key(best)[0]]
        if losers:
            return {"type": "play", "card": max(losers, key=low_key)}
        return {"type": "play", "card": min(legal, key=low_key)}

    @staticmethod
    def _legal(observation: dict) -> list:
        hand = observation["hand"]
        trick = [play["card"] for play in observation["trick"]]
        if not trick:
            if observation["trick_number"] == 0:
                return ["2c"] if "2c" in hand else []
            if observation["hearts_broken"]:
                return list(hand)
            return [card for card in hand if card[1] != "h"] or list(hand)
        follow = [card for card in hand if card[1] == trick[0][1]]
        return follow or list(hand)
