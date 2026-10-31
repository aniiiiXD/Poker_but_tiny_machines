"""A small, fast starter. No network or model calls during gameplay."""


class Agent:
    def act(self, observation: dict) -> dict:
        legal = observation["legal_actions"]
        cards = observation["hole_cards"]
        ranks = "23456789TJQKA"
        strength = sum(ranks.index(card[0]) + 2 for card in cards)
        pair = cards[0][0] == cards[1][0]
        if "raise" in legal and (pair or strength >= 25):
            return {"action": "raise", "amount": observation["min_raise"]}
        if "check" in legal:
            return {"action": "check"}
        if "call" in legal and (strength >= 17 or observation["to_call"] <= 20):
            return {"action": "call"}
        return {"action": "fold"}
