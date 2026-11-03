"""Deterministic Hearts baseline strategies.

Every baseline reads only the observation it is handed — never hidden state —
and derives any randomness from a seed fixed at construction, so a match is
replayable from (bots, seed) alone.
"""
from __future__ import annotations

import random

from .engine import QUEEN_SPADES, legal_plays, low_key, points_of


class HeartsBaseline:
    engine_hint = "hearts"

    def __init__(self, name: str, seed: int):
        self.name = name
        self._seed = seed

    def reset(self) -> None:
        self._rng = random.Random(f"{self._seed}:{self.name}")

    def act(self, observation: dict) -> dict:  # pragma: no cover - overridden
        raise NotImplementedError

    # -- shared helpers -------------------------------------------------
    def _legal(self, observation) -> list[str]:
        """Legal plays derived from the observation alone (same rules text)."""
        hand = observation["hand"]
        trick_cards = [play["card"] for play in observation["trick"]]
        return legal_plays(hand, trick_cards, observation["hearts_broken"],
                           observation["trick_number"])

    @staticmethod
    def _current_best(trick) -> str:
        """Highest card of the led suit currently winning the trick."""
        led_suit = trick[0]["card"][1]
        return max((play["card"] for play in trick if play["card"][1] == led_suit), key=low_key)

    def _pass(self, cards) -> dict:
        return {"type": "pass", "cards": list(cards)}

    def _play(self, card) -> dict:
        return {"type": "play", "card": card}


class SafeDumper(HeartsBaseline):
    """Sheds dangerous cards early and ducks under every trick it can."""

    @staticmethod
    def _danger(card):
        """High cards, hearts, and above all the Q♠ are dangerous to hold."""
        rank, suit = low_key(card)
        bonus = 6 if card == QUEEN_SPADES else 3 if card[1] == "h" else 2 if card[1] == "s" else 0
        return (rank + bonus, suit)

    def act(self, observation):
        hand = observation["hand"]
        if observation["turn"]["type"] == "pass":
            return self._pass(sorted(hand, key=self._danger, reverse=True)[:3])
        legal = self._legal(observation)
        trick = observation["trick"]
        if not trick:
            plain = [card for card in legal if card != QUEEN_SPADES] or legal
            return self._play(min(plain, key=low_key))
        best = low_key(self._current_best(trick))[0]
        if legal[0][1] != trick[0]["card"][1]:  # void in the led suit: dump danger
            return self._play(max(legal, key=self._danger))
        losers = [card for card in legal if low_key(card)[0] < best]
        if losers:
            return self._play(max(losers, key=self._danger))
        winners = [card for card in legal if low_key(card)[0] > best]
        safe = [card for card in winners if card != QUEEN_SPADES] or winners
        return self._play(min(safe, key=low_key))


class MoonHunter(HeartsBaseline):
    """Keeps its winners, hunts every penalty card, and shoots for the moon."""

    def act(self, observation):
        hand = observation["hand"]
        if observation["turn"]["type"] == "pass":
            pool = [card for card in hand if card[1] != "h" and card != QUEEN_SPADES]
            if len(pool) < 3:  # near-all-hearts hand: top up with the lowest points
                extras = sorted((card for card in hand if card not in pool), key=low_key)
                pool += extras[: 3 - len(pool)]
            return self._pass(sorted(pool, key=low_key)[:3])
        legal = self._legal(observation)
        trick = observation["trick"]
        if not trick:
            hunters = [card for card in legal if points_of(card) == 0] or legal
            return self._play(max(hunters, key=low_key))
        best = low_key(self._current_best(trick))[0]
        winners = [card for card in legal if card[1] == trick[0]["card"][1]
                   and low_key(card)[0] > best]
        if winners:
            return self._play(min(winners, key=low_key))  # take the trick, keep the points
        harmless = [card for card in legal if points_of(card) == 0]
        if harmless:
            return self._play(max(harmless, key=low_key))
        return self._play(min(legal, key=low_key))  # forced to shed points: shed the least


class QsDodger(HeartsBaseline):
    """Treats the Q♠ as radioactive: pass it, slough it, never win with it."""

    def act(self, observation):
        hand = observation["hand"]
        if observation["turn"]["type"] == "pass":
            if QUEEN_SPADES in hand:
                others = sorted((card for card in hand if card != QUEEN_SPADES),
                                key=low_key, reverse=True)
                return self._pass([QUEEN_SPADES, *others[:2]])
            return self._pass(sorted(hand, key=low_key, reverse=True)[:3])
        legal = self._legal(observation)
        trick = observation["trick"]
        if not trick:
            safe = [card for card in legal if card != QUEEN_SPADES] or legal
            return self._play(min(safe, key=low_key))
        best = low_key(self._current_best(trick))[0]
        if legal[0][1] != trick[0]["card"][1]:  # void: slough the Q♠, then a high heart
            if QUEEN_SPADES in legal:
                return self._play(QUEEN_SPADES)
            hearts = [card for card in legal if card[1] == "h"]
            return self._play(max(hearts or legal, key=low_key))
        if (trick[0]["card"][1] == "s" and QUEEN_SPADES in legal and best > low_key("Qs")[0]):
            return self._play(QUEEN_SPADES)  # duck under a higher spade with the queen
        losers = [card for card in legal if low_key(card)[0] < best]
        if losers:
            return self._play(max(losers, key=low_key))
        winners = [card for card in legal if low_key(card)[0] > best]
        safe = [card for card in winners if card != QUEEN_SPADES] or winners
        return self._play(min(safe, key=low_key))


class LowCardFloater(HeartsBaseline):
    """Floats the lowest legal card everywhere and lets others fight it out."""

    def act(self, observation):
        hand = observation["hand"]
        if observation["turn"]["type"] == "pass":
            pool = sorted(hand, key=low_key)
            if self._rng.random() < 0.2 and len(pool) > 3:
                pool[2], pool[3] = pool[3], pool[2]  # slight shuffle among the lowest
            return self._pass(pool[:3])
        legal = sorted(self._legal(observation), key=low_key)
        if self._rng.random() < 0.2 and len(legal) > 1:
            return self._play(legal[1])
        return self._play(legal[0])


FAMILIES = (SafeDumper, MoonHunter, QsDodger, LowCardFloater)


def make_hearts_baselines(count: int = 4, seed: int = 0) -> list:
    if not 0 <= count <= len(FAMILIES):
        raise ValueError("Hearts has between 0 and 4 baseline strategies.")
    names = ("Dumper", "MoonHunter", "Dodger", "Floater")
    bots = []
    for index in range(count):
        bot = FAMILIES[index](names[index], seed)
        bot.reset()
        bots.append(bot)
    return bots
