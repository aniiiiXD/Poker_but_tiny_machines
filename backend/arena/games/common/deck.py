"""Shared card/token engine for Stack Theory games.

The one deck every deck game builds on (TICKET-001): contract card identity,
seeded shuffling, drawing, discarding, round-robin dealing, sorted hands, and
face-down piles. Card IDs follow `GAMES_CONTRACT.md` section 2 — unique
strings ``"{rank}{suit}"`` with ranks ``A23456789TJQK`` and suits ``cdhs`` —
but every structure here treats its tokens as opaque strings, so non-card
games can reuse the same machinery.

Determinism: nothing here touches the global ``random`` module. All
randomness flows from a private ``random.Random`` instance seeded by the
caller, and ``Deck.reseed`` re-pins that stream at any point. Everything
passed in and out is plain strings and lists, JSON-serializable as-is.
"""
from __future__ import annotations

import random
from collections.abc import Callable, Iterable, Iterator

RANKS = "A23456789TJQK"  # contract rank order: A -> 2 -> ... -> K
SUITS = "cdhs"           # contract suit order: clubs, diamonds, hearts, spades

SortKey = Callable[[str], tuple[int, int]]


def contract_sort_key(card: str) -> tuple[int, int]:
    """Contract card ordering: rank first, then suit (used for tidy hands)."""
    return (RANKS.index(card[0]), SUITS.index(card[1]))


def standard_deck() -> list[str]:
    """The 52 contract cards, rank-major then suit-minor (Ac, Ad, ... Ks)."""
    return [rank + suit for rank in RANKS for suit in SUITS]


class Deck:
    """A draw stack of opaque tokens with seeded, reproducible shuffling.

    The top of the deck is the front of the token list: ``draw`` pops from
    the front and ``discard`` returns cards to the back (the bottom). The
    deck never shuffles by itself — call ``shuffle`` when the game says
    chance happens, and ``reseed`` to re-pin the stream mid-game.
    """

    def __init__(self, tokens: Iterable[str], seed: int) -> None:
        """Copy ``tokens`` and seed a private Random used by every shuffle."""
        self._tokens: list[str] = list(tokens)
        self._rng = random.Random(seed)

    def shuffle(self) -> None:
        """Re-randomize the order of the remaining tokens from the stored seed."""
        self._rng.shuffle(self._tokens)

    def reseed(self, seed: int) -> None:
        """Swap in a fresh ``random.Random(seed)`` so later shuffles replay."""
        self._rng = random.Random(seed)

    def draw(self, n: int = 1) -> list[str]:
        """Remove and return the top ``n`` tokens in draw order.

        Raises ValueError when the deck holds fewer than ``n`` tokens; the
        deck is left untouched in that case.
        """
        if n < 0:
            raise ValueError(f"cannot draw {n} tokens.")
        if n > len(self._tokens):
            raise ValueError(f"cannot draw {n} tokens; only {len(self._tokens)} remain.")
        drawn = self._tokens[:n]
        del self._tokens[:n]
        return drawn

    def discard(self, cards: str | Iterable[str]) -> None:
        """Append cards to the bottom of the deck so they can be drawn again."""
        self._tokens.extend([cards] if isinstance(cards, str) else cards)

    @property
    def remaining(self) -> int:
        """How many tokens are left in the deck."""
        return len(self._tokens)

    def deal(self, seats: int) -> list[Hand]:
        """Deal every remaining token round-robin into ``seats`` hands.

        The top token goes to seat 0, the next to seat 1, and so on, wrapping
        around. When the count does not divide evenly, the first
        ``len(tokens) % seats`` seats receive one extra card, the way a human
        dealer deals around the table. The deck is left empty and every hand
        is sorted under the contract key.
        """
        if seats < 1:
            raise ValueError("must deal to at least one seat.")
        tokens, self._tokens = self._tokens, []
        return [Hand(tokens[seat::seats]) for seat in range(seats)]


class Hand:
    """An ordered multiset of card IDs, kept sorted for tidy display.

    The hand is always sorted under its sort key — the contract key unless a
    custom one is installed via ``sort`` — so ``add`` keeps order without the
    caller thinking about it. Duplicate cards are allowed (it is a multiset).
    """

    def __init__(self, cards: Iterable[str] | None = None, key: SortKey | None = None) -> None:
        """Copy ``cards`` and sort them under ``key`` (contract key if None)."""
        self._key: SortKey = contract_sort_key if key is None else key
        self._cards: list[str] = list(cards) if cards is not None else []
        self._cards.sort(key=self._key)

    def add(self, card: str) -> None:
        """Insert one card, keeping the hand sorted under its sort key."""
        self._cards.append(card)
        self._cards.sort(key=self._key)

    def remove(self, card: str) -> None:
        """Remove one copy of ``card``; KeyError when the hand does not hold it."""
        if card not in self._cards:
            raise KeyError(card)
        self._cards.remove(card)

    def __contains__(self, card: object) -> bool:
        return card in self._cards

    def count(self, card: str) -> int:
        """How many copies of ``card`` the hand holds."""
        return self._cards.count(card)

    def sort(self, key: SortKey | None = None) -> None:
        """Re-sort the hand; a key passed here also becomes the hand's key."""
        if key is not None:
            self._key = key
        self._cards.sort(key=self._key)

    def to_list(self) -> list[str]:
        """Plain list copy in hand order, JSON-serializable as-is."""
        return list(self._cards)

    def __len__(self) -> int:
        return len(self._cards)

    def __iter__(self) -> Iterator[str]:
        return iter(self._cards)


class Pile:
    """A face-down stack of card IDs in played order.

    The first card added sits at the bottom of the pile; ``take_all``
    returns everything bottom-up, i.e. in the order it was played, and
    empties the pile — the shape Bluff-style pickups and trick collectors
    need.
    """

    def __init__(self, cards: Iterable[str] | None = None) -> None:
        """Start the pile with ``cards`` (bottom first), or empty."""
        self._cards: list[str] = list(cards) if cards is not None else []

    def add(self, cards: str | Iterable[str]) -> None:
        """Put cards on top of the pile, preserving played order."""
        self._cards.extend([cards] if isinstance(cards, str) else cards)

    def take_all(self) -> list[str]:
        """Remove and return the whole pile in played order, leaving it empty."""
        cards, self._cards = self._cards, []
        return cards

    @property
    def size(self) -> int:
        """How many cards are currently face-down in the pile."""
        return len(self._cards)
