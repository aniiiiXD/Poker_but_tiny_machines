"""Deterministic Bluff baseline strategies.

Every baseline reads only the observation it is handed — never hidden state —
and derives any randomness from a seed fixed at construction, so a match is
replayable from (bots, seed) alone.
"""
from __future__ import annotations

import random

from .engine import sort_key


class BluffBaseline:
    engine_hint = "bluff"

    def __init__(self, name: str, seed: int):
        self.name = name
        self._seed = seed

    def reset(self) -> None:
        self._rng = random.Random(f"{self._seed}:{self.name}")

    # -- shared helpers -------------------------------------------------
    @staticmethod
    def _rank_count(hand, rank):
        return sum(1 for card in hand if card[0] == rank)

    @staticmethod
    def _revealed_rank_count(history, rank):
        """Cards of `rank` already exposed in publicly revealed batches."""
        return sum(
            1
            for event in history
            if event.get("type") == "resolution" and event.get("revealed")
            for card in event["revealed"]
            if card[0] == rank
        )

    def _lowest(self, hand):
        return sorted(hand, key=sort_key)[0]

    def act(self, observation: dict) -> dict:  # pragma: no cover - overridden
        raise NotImplementedError


class Honest(BluffBaseline):
    """Truthful whenever possible; challenges only with proof of impossibility."""

    def act(self, observation):
        turn = observation["turn"]
        hand = observation["hand"]
        if turn["type"] == "play":
            rank = observation["required_rank"]
            owned = [card for card in hand if card[0] == rank]
            if owned:
                cards = sorted(owned, key=sort_key)[: 1 + self._rng.randrange(min(3, len(owned)))]
                return {"type": "play", "cards": cards}
            return {"type": "play", "cards": [self._lowest(hand)]}
        # Challenge only when every card of the required rank is in this hand,
        # so the claimant cannot hold any truthful card.
        rank = turn["rank"]
        revealed = self._revealed_rank_count(observation["history"], rank)
        if self._rank_count(hand, rank) + revealed >= 4:
            return {"type": "challenge"}
        return {"type": "pass"}


class Random(BluffBaseline):
    """Uniformly random legal moves; a calibration opponent, not a strategist."""

    def act(self, observation):
        turn = observation["turn"]
        hand = observation["hand"]
        if turn["type"] == "play":
            count = 1 + self._rng.randrange(min(4, len(hand)))
            return {"type": "play", "cards": self._rng.sample(hand, count)}
        if self._rng.random() < 0.3:
            return {"type": "challenge"}
        return {"type": "pass"}


class Counter(BluffBaseline):
    """Count-aware: challenges when the claim is arithmetically impossible."""

    def act(self, observation):
        turn = observation["turn"]
        hand = observation["hand"]
        if turn["type"] == "play":
            rank = observation["required_rank"]
            owned = [card for card in hand if card[0] == rank]
            if owned:
                return {"type": "play", "cards": sorted(owned, key=sort_key)[:2]}
            return {"type": "play", "cards": [self._lowest(hand)]}
        rank = turn["rank"]
        # declared + own + publicly revealed cannot exceed the 4 copies of a
        # rank in the deck without a lie.
        impossible = turn["count"] + self._rank_count(hand, rank) + \
            self._revealed_rank_count(observation["history"], rank) > 4
        if impossible or (turn["count"] >= 3 and observation["pile_size"] >= 10):
            return {"type": "challenge"}
        return {"type": "pass"}


class Liar(BluffBaseline):
    """Max-size claims, frequent challenges; stress-tests the challengers."""

    def act(self, observation):
        turn = observation["turn"]
        hand = observation["hand"]
        if turn["type"] == "play":
            count = min(4, len(hand))
            return {"type": "play", "cards": self._rng.sample(hand, count)}
        if self._rng.random() < 0.5:
            return {"type": "challenge"}
        return {"type": "pass"}


FAMILIES = (Honest, Random, Counter, Liar)


def make_bluff_baselines(count: int = 4, seed: int = 0) -> list:
    if not 0 <= count <= len(FAMILIES):
        raise ValueError("Bluff has between 0 and 4 baseline strategies.")
    names = ("Honest", "Random", "Counter", "Liar")
    bots = []
    for index in range(count):
        bot = FAMILIES[index](names[index], seed)
        bot.reset()
        bots.append(bot)
    return bots
