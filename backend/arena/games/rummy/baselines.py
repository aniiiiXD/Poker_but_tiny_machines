"""Deterministic Rummy baseline strategies.

Every baseline reads only the observation it is handed — never hidden state —
and derives any randomness from a seed fixed at construction, so a match is
replayable from (bots, seed) alone. All four declare the moment the engine's
validator confirms their 14 cards form a legal declaration, and differ in how
they draw, what they shed, and how they treat jokers.
"""
from __future__ import annotations

import random

from .engine import RANKS, card_points, is_joker, sort_key, valid_declaration


class RummyBaseline:
    engine_hint = "rummy"

    def __init__(self, name: str, seed: int):
        self.name = name
        self._seed = seed

    def reset(self) -> None:
        self._rng = random.Random(f"{self._seed}:{self.name}")

    # -- shared helpers -------------------------------------------------
    @staticmethod
    def _rank_mates(card, hand, wild):
        """Other naturals sharing the card's rank."""
        if is_joker(card, wild):
            return []
        return [
            other for other in hand
            if other != card and not is_joker(other, wild) and other[0] == card[0]
        ]

    @staticmethod
    def _suit_neighbors(card, hand, wild):
        """Naturals of the same suit within two ranks (a joker bridges one gap)."""
        if is_joker(card, wild):
            return []
        return [
            other for other in hand
            if other != card and not is_joker(other, wild) and other[1] == card[1]
            and abs(RANKS.index(other[0]) - RANKS.index(card[0])) <= 2
        ]

    def _links(self, card, hand, wild):
        return len(self._rank_mates(card, hand, wild)) + len(self._suit_neighbors(card, hand, wild))

    def _loose_naturals(self, hand, wild):
        """Naturals with no rank mate and no suit neighbor."""
        return [
            card for card in hand
            if not is_joker(card, wild)
            and not self._rank_mates(card, hand, wild)
            and not self._suit_neighbors(card, hand, wild)
        ]

    def _declare_or_pass(self, observation):
        hand = observation["hand"]
        groups = valid_declaration(hand, observation["wild_rank"])
        if groups is not None:
            return {"type": "declare", "hand": list(hand)}
        return {"type": "pass"}

    def _shed(self, hand, wild, loose_key, fallback_key):
        """Deterministic discard: prefer the loosest naturals, fall back to the
        least connected natural, and only touch jokers when nothing else exists."""
        loose = self._loose_naturals(hand, wild)
        if loose:
            return max(loose, key=loose_key)
        naturals = [card for card in hand if not is_joker(card, wild)]
        pool = naturals or list(hand)
        return min(pool, key=fallback_key)


class Collector(RummyBaseline):
    """Meld-first: pulls from the stock, sheds the loosest high cards, shows fast."""

    def act(self, observation):
        turn = observation["turn"]
        hand = observation["hand"]
        wild = observation["wild_rank"]
        if turn["type"] == "draw":
            if observation["stock_remaining"] > 0:
                return {"type": "draw", "from": "stock"}
            return {"type": "draw", "from": "discard"}
        if turn["type"] == "declare":
            return self._declare_or_pass(observation)
        card = self._shed(
            hand, wild,
            loose_key=lambda c: (card_points(c, wild), sort_key(c)),
            fallback_key=lambda c: (self._links(c, hand, wild), -card_points(c, wild), sort_key(c)),
        )
        return {"type": "discard", "card": card}


class Pressure(RummyBaseline):
    """Discard-pressure: snatches useful upcards to deny them, dumps cards
    that do not feed the rank the table is obviously fishing for."""

    def _upcard_helps(self, top, hand, wild):
        if is_joker(top, wild):
            return True
        for card in hand:
            if is_joker(card, wild):
                continue
            if card[0] == top[0]:
                return True
            if card[1] == top[1] and abs(RANKS.index(card[0]) - RANKS.index(top[0])) <= 2:
                return True
        return False

    def act(self, observation):
        turn = observation["turn"]
        hand = observation["hand"]
        wild = observation["wild_rank"]
        top = observation["discard_top"]
        if turn["type"] == "draw":
            helps = top is not None and self._upcard_helps(top, hand, wild)
            # A public joker is worth a denial gamble a quarter of the time.
            gamble = (top is not None and is_joker(top, wild) and self._rng.random() < 0.25)
            if helps or gamble:
                return {"type": "draw", "from": "discard"}
            if observation["stock_remaining"] > 0:
                return {"type": "draw", "from": "stock"}
            return {"type": "draw", "from": "discard"}
        if turn["type"] == "declare":
            return self._declare_or_pass(observation)
        pool = self._loose_naturals(hand, wild)
        if top is not None and not is_joker(top, wild):
            safe = [card for card in pool if card[0] != top[0]] or pool
        else:
            safe = pool
        if safe:
            card = max(safe, key=lambda c: (card_points(c, wild), sort_key(c)))
        else:
            card = self._shed(
                hand, wild,
                loose_key=lambda c: (card_points(c, wild), sort_key(c)),
                fallback_key=lambda c: (self._links(c, hand, wild), -card_points(c, wild), sort_key(c)),
            )
        return {"type": "discard", "card": card}


class Hoarder(RummyBaseline):
    """Joker-hoarder: never releases a joker, sheds the cheapest naturals,
    and shows the moment its wild cards can bridge two sequences."""

    def act(self, observation):
        turn = observation["turn"]
        hand = observation["hand"]
        wild = observation["wild_rank"]
        if turn["type"] == "draw":
            if observation["stock_remaining"] > 0:
                return {"type": "draw", "from": "stock"}
            return {"type": "draw", "from": "discard"}
        if turn["type"] == "declare":
            return self._declare_or_pass(observation)
        naturals = [card for card in hand if not is_joker(card, wild)]
        if not naturals:
            return {"type": "discard", "card": min(hand)}
        card = min(
            naturals,
            key=lambda c: (self._links(c, hand, wild), card_points(c, wild), sort_key(c)),
        )
        return {"type": "discard", "card": card}


class Chaser(RummyBaseline):
    """Chaser-of-discard: lives on the public upcard, taking whatever the
    table throws away and re-dumping the biggest natural it did not draw."""

    def act(self, observation):
        turn = observation["turn"]
        hand = observation["hand"]
        wild = observation["wild_rank"]
        if turn["type"] == "draw":
            if observation["discard_top"] is not None:
                return {"type": "draw", "from": "discard"}
            return {"type": "draw", "from": "stock"}
        if turn["type"] == "declare":
            return self._declare_or_pass(observation)
        just_drew = None
        for event in reversed(observation["history"]):
            if event.get("type") == "draw" and event.get("seat") == observation["seat"]:
                just_drew = event.get("card")
                break
        pool = [
            card for card in hand
            if not is_joker(card, wild) and card != just_drew
        ] or [card for card in hand if card != just_drew] or list(hand)
        card = max(pool, key=lambda c: (card_points(c, wild), sort_key(c)))
        return {"type": "discard", "card": card}


FAMILIES = (Collector, Pressure, Hoarder, Chaser)
NAMES = ("Collector", "Pressure", "Hoarder", "Chaser")


def make_rummy_baselines(count: int = 4, seed: int = 0) -> list:
    """The four baseline strategies, cycled with distinct names for tables
    bigger than four (Rummy seats 2–6)."""
    if not 0 <= count <= 6:
        raise ValueError("Rummy tables seat 2 to 6; between 0 and 6 baselines.")
    bots = []
    for index in range(count):
        family = FAMILIES[index % len(FAMILIES)]
        name = NAMES[index % len(NAMES)]
        if index >= len(FAMILIES):
            name = f"{name} {index + 1}"
        bot = family(name, seed)
        bot.reset()
        bots.append(bot)
    return bots
