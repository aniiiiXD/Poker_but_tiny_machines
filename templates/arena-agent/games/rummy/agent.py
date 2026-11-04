"""A small, readable Rummy starter. No network or model calls during gameplay.

Rummy protocol 1 observations you receive (see GAMES_CONTRACT.md §10):
  hand            your 13 (or 14) cards, e.g. ["Ac", "9d", "XJ1"]
  wild_rank       every card of this rank plays as a joker (public)
  players         seat/name/card-count for every player (no hidden cards!)
  stock_remaining cards left in the closed stock
  discard_top     the public upcard (None while the pile is momentarily empty)
  discard_size    how deep the discard pile is
  turn            {"type": "draw"} | {"type": "declare"} | {"type": "discard"}
  history         public events: draws, discards, reshuffles, wrong shows

Return one of:
  {"type": "draw", "from": "stock" | "discard"}
  {"type": "declare", "hand": [the 14 card ids you own]}   only at 14 cards
  {"type": "pass"}                                         at the declare turn
  {"type": "discard", "card": id}                          one card you own

Invalid actions are recorded as faults and replaced with a deterministic
fallback (draw from stock, pass, discard your lowest card), so always answer
something legal. A wrong declaration (14 cards that cannot form two
sequences, one pure) also costs a fault plus 20 cap points — this starter
only declares when it has verified a full grouping itself.
"""

from itertools import combinations as _combinations

RANKS = "A23456789TJQK"
SUITS = "cdhs"
JOKER_CARDS = ("XJ1", "XJ2")
LOW_POS = {rank: index for index, rank in enumerate(RANKS)}
HIGH_POS = {rank: (index - 1) % 13 for index, rank in enumerate(RANKS)}


def _is_joker(card, wild_rank):
    return card in JOKER_CARDS or card[0] == wild_rank


def _sort_key(card):
    """Contract order; printed jokers sort after every natural."""
    if card in JOKER_CARDS:
        return (len(RANKS), 0)
    return (RANKS.index(card[0]), SUITS.index(card[1]))


def _card_points(card, wild_rank):
    if _is_joker(card, wild_rank):
        return 0
    return 10 if card[0] in "TJQKA" else int(card[0])


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
    """A verified grouping of the whole hand, or None.

    A small exact-cover search over melds (the same shape the engine
    validates with): every card lands in exactly one verified meld, at least
    two groups are sequences and one of them pure. Only a fully verified
    grouping is ever declared, so a wrong declaration can not happen.
    """
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
    def act(self, observation: dict) -> dict:
        turn = observation["turn"]
        hand = observation["hand"]
        wild = observation["wild_rank"]
        if turn["type"] == "draw":
            top = observation["discard_top"]
            if top is not None and self._upcard_helps(top, hand, wild):
                return {"type": "draw", "from": "discard"}
            if observation["stock_remaining"] > 0:
                return {"type": "draw", "from": "stock"}
            return {"type": "draw", "from": "discard"}
        if turn["type"] == "declare":
            groups = _try_declaration(hand, wild)
            if groups is not None:
                return {"type": "declare", "hand": list(hand)}
            return {"type": "pass"}
        loose = [
            card for card in hand
            if not _is_joker(card, wild)
            and not self._rank_mates(card, hand, wild)
            and not self._suit_neighbors(card, hand, wild)
        ]
        if loose:
            card = max(loose, key=lambda c: (_card_points(c, wild), _sort_key(c)))
        else:
            naturals = [card for card in hand if not _is_joker(card, wild)] or list(hand)
            card = min(
                naturals,
                key=lambda c: (self._links(c, hand, wild), -_card_points(c, wild), _sort_key(c)),
            )
        return {"type": "discard", "card": card}

    @staticmethod
    def _rank_mates(card, hand, wild):
        if _is_joker(card, wild):
            return []
        return [c for c in hand if c != card and not _is_joker(c, wild) and c[0] == card[0]]

    @staticmethod
    def _suit_neighbors(card, hand, wild):
        if _is_joker(card, wild):
            return []
        return [
            c for c in hand
            if c != card and not _is_joker(c, wild) and c[1] == card[1]
            and abs(RANKS.index(c[0]) - RANKS.index(card[0])) <= 2
        ]

    @staticmethod
    def _links(card, hand, wild):
        return len(Agent._rank_mates(card, hand, wild)) + len(Agent._suit_neighbors(card, hand, wild))

    @staticmethod
    def _upcard_helps(top, hand, wild):
        if _is_joker(top, wild):
            return True
        for card in hand:
            if _is_joker(card, wild):
                continue
            if card[0] == top[0]:
                return True
            if card[1] == top[1] and abs(RANKS.index(card[0]) - RANKS.index(top[0])) <= 2:
                return True
        return False
