"""Example CPU model agent for Stack Theory Rummy v1.

A tiny linear keep-score model over hand-crafted per-card features, driven by
weights.json so you can replace the numbers without touching code. Uses only
NumPy and the observation it receives — never hidden state. Declarations are
verified with the same bounded meld search the rules use, so this agent can
never make a wrong show; the model's job is drawing and shedding.
"""
import json
from itertools import combinations as _combinations
from pathlib import Path

import numpy as np

RANKS = "A23456789TJQK"
SUITS = "cdhs"
JOKER_CARDS = ("XJ1", "XJ2")
LOW_POS = {rank: index for index, rank in enumerate(RANKS)}
HIGH_POS = {rank: (index - 1) % 13 for index, rank in enumerate(RANKS)}
FEATURES = ("bias", "points", "rank_mates", "suit_neighbors", "joker")


def _is_joker(card, wild_rank):
    return card in JOKER_CARDS or card[0] == wild_rank


def _card_points(card, wild_rank):
    if _is_joker(card, wild_rank):
        return 0
    return 10 if card[0] in "TJQKA" else int(card[0])


def _features(card, hand, wild_rank):
    """Per-card keep-score features: how much this card looks like a keeper."""
    if _is_joker(card, wild_rank):
        return np.array([1.0, 0.0, 0.0, 0.0, 1.0])
    mates = sum(1 for c in hand if c != card and not _is_joker(c, wild_rank) and c[0] == card[0])
    neighbors = sum(
        1 for c in hand
        if c != card and not _is_joker(c, wild_rank) and c[1] == card[1]
        and abs(LOW_POS[c[0]] - LOW_POS[card[0]]) <= 2
    )
    return np.array([
        1.0,
        _card_points(card, wild_rank) / 10.0,
        float(mates),
        float(neighbors),
        0.0,
    ])


def _classify(group, wild_rank):
    """'pure' | 'impure' | 'set' for a legal meld, else None (see RULES.md)."""
    if len(group) < 3 or len(set(group)) != len(group):
        return None
    naturals = [card for card in group if not _is_joker(card, wild_rank)]
    jokers = len(group) - len(naturals)
    if not naturals or jokers > 2:
        return None
    ranks = {card[0] for card in naturals}
    if len(ranks) == 1:
        if len(group) <= 4 and len({card[1] for card in naturals}) == len(naturals):
            return "set"
        return None
    if len({card[1] for card in naturals}) != 1 or len(ranks) != len(naturals):
        return None
    for positions in (LOW_POS, HIGH_POS):
        ordered = sorted(ranks, key=positions.__getitem__)
        if positions[ordered[-1]] - positions[ordered[0]] + 1 <= len(group):
            return "impure" if jokers else "pure"
    return None


def _meld_candidates(anchor, cards, jokers, wild_rank):
    """Every valid meld made of `cards` that contains `anchor` (fixed order)."""
    pool = sorted(jokers, key=lambda card: (card != anchor, card))
    naturals_by_suit = {}
    for card in cards:
        if not _is_joker(card, wild_rank):
            naturals_by_suit.setdefault(card[1], {}).setdefault(card[0], card)
    out = []
    seen = set()

    def offer(meld):
        if tuple(meld) not in seen:
            seen.add(tuple(meld))
            out.append(meld)

    def sequence_melds(base, ranks, rank_map, min_jokers):
        base_ranks = {card[0] for card in base}
        extra = [rank for rank in ranks if rank not in base_ranks]
        for count in range(len(extra) + 1):
            for combo in _combinations(extra, count):
                chosen = base + [rank_map[rank] for rank in combo]
                if not chosen:
                    continue
                size = len(chosen)
                all_ranks = base_ranks | set(combo)
                span = min(
                    max(POS[rank] for rank in all_ranks)
                    - min(POS[rank] for rank in all_ranks) + 1
                    for POS in (LOW_POS, HIGH_POS)
                )
                for j in range(max(min_jokers, 3 - size, span - size), min(2, len(pool)) + 1):
                    offer(chosen + pool[:j])

    def set_melds(base, extras, min_jokers):
        for count in range(len(extras) + 1):
            for combo in _combinations(extras, count):
                chosen = base + list(combo)
                if not chosen:
                    continue
                size = len(chosen)
                for j in range(max(min_jokers, 3 - size), min(2, 4 - size, len(pool)) + 1):
                    offer(chosen + pool[:j])

    if _is_joker(anchor, wild_rank):
        for suit in sorted(naturals_by_suit):
            rank_map = naturals_by_suit[suit]
            sequence_melds([], sorted(rank_map, key=LOW_POS.__getitem__), rank_map, 1)
        by_rank = {}
        for suit in sorted(naturals_by_suit):
            for rank, card in naturals_by_suit[suit].items():
                by_rank.setdefault(rank, []).append(card)
        for rank in sorted(by_rank, key=LOW_POS.__getitem__):
            set_melds([], sorted(by_rank[rank]), 1)
    else:
        rank_map = naturals_by_suit.get(anchor[1], {})
        sequence_melds([anchor], sorted(rank_map, key=LOW_POS.__getitem__), rank_map, 0)
        mates = [
            naturals_by_suit[suit][anchor[0]]
            for suit in sorted(naturals_by_suit)
            if anchor[0] in naturals_by_suit[suit]
        ]
        set_melds([anchor], [m for m in mates if m != anchor], 0)
    return out


def _try_declaration(hand, wild_rank, budget=4000):
    """A verified full grouping into a legal declaration shape, or None."""
    cards = sorted(
        hand,
        key=lambda c: (1 if _is_joker(c, wild_rank) else 0, LOW_POS.get(c[0], 13), c),
    )
    state = [budget]

    def meets(groups):
        kinds = [_classify(group, wild_rank) for group in groups]
        runs = [kind for kind in kinds if kind in ("pure", "impure")]
        return len(runs) >= 2 and "pure" in kinds

    def search(rest, acc):
        if not rest:
            return list(acc) if meets(acc) else None
        if state[0] <= 0:
            return None
        state[0] -= 1
        anchor = rest[0]
        rest_jokers = [card for card in rest if _is_joker(card, wild_rank)]
        rest_naturals = [card for card in rest if not _is_joker(card, wild_rank)]
        for meld in _meld_candidates(anchor, rest_naturals, rest_jokers, wild_rank):
            leftover = list(rest)
            for card in meld:
                leftover.remove(card)
            tail = search(leftover, acc + [meld])
            if tail is not None:
                return tail
        return None

    return search(cards, [])


class Agent:
    def __init__(self):
        self.weights = json.loads(Path(__file__).with_name("weights.json").read_text())
        self.w = np.array([self.weights[name] for name in FEATURES])

    def _keep_scores(self, hand, wild_rank):
        """Higher keep-score = the model wants to hold this card."""
        matrix = np.array([_features(card, hand, wild_rank) for card in hand])
        return matrix @ self.w

    def act(self, observation):
        turn = observation["turn"]
        hand = observation["hand"]
        wild = observation["wild_rank"]
        if turn["type"] == "draw":
            top = observation["discard_top"]
            if top is not None:
                takeover = float(_features(top, hand, wild) @ self.w)
                if takeover >= self.weights["take_threshold"]:
                    return {"type": "draw", "from": "discard"}
            if observation["stock_remaining"] > 0:
                return {"type": "draw", "from": "stock"}
            return {"type": "draw", "from": "discard"}
        if turn["type"] == "declare":
            if _try_declaration(hand, wild) is not None:
                return {"type": "declare", "hand": list(hand)}
            return {"type": "pass"}
        # Discard the lowest-keep-score natural; jokers are near-unkeepable only
        # when the weights say so (the default weights hoard them).
        scores = self._keep_scores(hand, wild)
        order = np.argsort(scores, kind="stable")
        for index in order:
            if hand[index] not in JOKER_CARDS:
                return {"type": "discard", "card": hand[index]}
        return {"type": "discard", "card": hand[int(order[0])]}
