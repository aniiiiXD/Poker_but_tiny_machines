"""Deterministic UNO baseline strategies.

Every baseline reads only the observation it is handed — never hidden state —
and derives any randomness from a seed fixed at construction, so a match is
replayable from (bots, seed) alone. All four handle every decision window the
engine can issue: play, post-draw, penalty, UNO declaration, and the wild
draw four challenge.
"""
from __future__ import annotations

import random

from .engine import COLORS, card_color, card_face, is_wild, matches, sort_key


class UnoBaseline:
    engine_hint = "uno"

    def __init__(self, name: str, seed: int):
        self.name = name
        self._seed = seed

    def reset(self) -> None:
        self._rng = random.Random(f"{self._seed}:{self.name}")

    # -- shared helpers -------------------------------------------------
    @staticmethod
    def _legal(observation):
        hand = observation["hand"]
        top = observation["discard_top"]
        color = observation["active_color"]
        return [card for card in hand if matches(card, top, color)]

    @staticmethod
    def _dominant(hand):
        """The color this seat holds most of; ties resolve in r,y,g,b order."""
        counts = {color: sum(1 for card in hand if card_color(card) == color)
                  for color in COLORS}
        return max(COLORS, key=lambda color: counts[color])

    def _wild_play(self, observation, card):
        return {"type": "play", "card": card, "color": self._dominant(observation["hand"])}

    def act(self, observation: dict) -> dict:  # pragma: no cover - overridden
        raise NotImplementedError


class Dumper(UnoBaseline):
    """Sheds cards as fast as legal play allows; wilds go the moment nothing natural fits."""

    def act(self, observation):
        turn = observation["turn"]
        if turn["type"] == "play":
            legal = self._legal(observation)
            naturals = [card for card in legal if not is_wild(card)]
            if naturals:
                return {"type": "play", "card": naturals[0]}
            if legal:
                return self._wild_play(observation, legal[0])
            return {"type": "draw"}
        if turn["type"] == "post_draw":
            card = turn["card"]
            if is_wild(card):
                return self._wild_play(observation, card)
            return {"type": "play", "card": card}
        if turn["type"] == "penalty":
            return {"type": "draw"}
        if turn["type"] == "uno":
            return {"type": "uno"}
        if self._rng.random() < 0.15:
            return {"type": "challenge"}
        return {"type": "pass"}


class Holder(UnoBaseline):
    """Holds wilds until no natural card fits and prefers its dominant color."""

    def act(self, observation):
        turn = observation["turn"]
        hand = observation["hand"]
        if turn["type"] == "play":
            legal = self._legal(observation)
            naturals = [card for card in legal if not is_wild(card)]
            if naturals:
                dominant = [card for card in naturals
                            if card_color(card) == self._dominant(hand)]
                pick = dominant or naturals
                return {"type": "play", "card": min(pick, key=sort_key)}
            if legal:  # only wilds fit: time to let one go
                return self._wild_play(observation, legal[0])
            return {"type": "draw"}
        if turn["type"] == "post_draw":
            card = turn["card"]
            if not is_wild(card):
                return {"type": "play", "card": card}
            return {"type": "pass"}  # hoard the wild
        if turn["type"] == "penalty":
            return {"type": "draw"}
        if turn["type"] == "uno":
            return {"type": "uno"}
        own = observation["players"][observation["seat"]]["count"]
        if own <= 2 or self._rng.random() < 0.2:
            return {"type": "challenge"}
        return {"type": "pass"}


class Attacker(UnoBaseline):
    """Leads with penalty cards and shoots wild draw fours at every chance."""

    def act(self, observation):
        turn = observation["turn"]
        if turn["type"] == "play":
            legal = self._legal(observation)
            if legal:
                priority = {"draw2": 0, "skip": 1, "reverse": 2, "wild4": 3, "wild": 4}

                def rank(card):
                    return (priority.get(card_face(card), 5), sort_key(card))

                card = min(legal, key=rank)
                if is_wild(card):
                    return self._wild_play(observation, card)
                return {"type": "play", "card": card}
            return {"type": "draw"}
        if turn["type"] == "post_draw":
            card = turn["card"]
            if is_wild(card):
                return self._wild_play(observation, card)
            return {"type": "play", "card": card}
        if turn["type"] == "penalty":
            return {"type": "draw"}
        if turn["type"] == "uno":
            return {"type": "uno"}
        if self._rng.random() < 0.5:
            return {"type": "challenge"}
        return {"type": "pass"}


class Hoarder(UnoBaseline):
    """Plays from its dominant color wherever possible and hoards its wilds."""

    def act(self, observation):
        turn = observation["turn"]
        hand = observation["hand"]
        if turn["type"] == "play":
            legal = self._legal(observation)
            dominant = self._dominant(hand)
            from_dominant = [card for card in legal
                             if card_color(card) == dominant and not is_wild(card)]
            other = [card for card in legal
                     if card_color(card) != dominant and not is_wild(card)]
            numbers = [card for card in from_dominant if card_face(card).isdigit()]
            pick = numbers or from_dominant or other
            if pick:
                return {"type": "play", "card": min(pick, key=sort_key)}
            if legal:  # wilds only: hoarding is over
                return self._wild_play(observation, legal[0])
            return {"type": "draw"}
        if turn["type"] == "post_draw":
            card = turn["card"]
            if not is_wild(card):
                return {"type": "play", "card": card}
            return {"type": "pass"}  # hoard the wild
        if turn["type"] == "penalty":
            return {"type": "draw"}
        if turn["type"] == "uno":
            return {"type": "uno"}
        if self._rng.random() < 0.1:
            return {"type": "challenge"}
        return {"type": "pass"}


FAMILIES = (Dumper, Holder, Attacker, Hoarder)


def make_uno_baselines(count: int = 4, seed: int = 0) -> list:
    if not 0 <= count <= len(FAMILIES):
        raise ValueError("UNO has between 0 and 4 baseline strategies.")
    names = ("Dumper", "Holder", "Attacker", "Hoarder")
    bots = []
    for index in range(count):
        bot = FAMILIES[index](names[index], seed)
        bot.reset()
        bots.append(bot)
    return bots
