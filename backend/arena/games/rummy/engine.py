"""Stack Theory Rummy v1 — deterministic 13-card Indian Rummy for 2–6 seats.

Written to the frozen contract in `GAMES_CONTRACT.md` section 10 and the
rule sheet in `RULES.md` next to this file. Deterministic given (bots,
seed): the 106-card shoe is shuffled once through the shared deck engine,
the public wild rank is flipped from the stock, and every agent decision
either succeeds or falls back along a fixed rule. Hidden state — opponent
hands, the stock order, and the discard pile below its top card — never
enters an observation or a public replay frame.
"""
from __future__ import annotations

import random
from itertools import combinations

from ...sandbox import SandboxDown
from ..common.deck import RANKS, SUITS, Deck, Hand, standard_deck

PROTOCOL = 1
GAME_ID = "rummy"
RULES_VERSION = 1
SEATS = (2, 3, 4, 5, 6)
DECISION_CAP = 500
HAND_SIZE = 13
JOKER_CARDS = ("XJ1", "XJ2")
JOKERS_PER_MELD = 2          # RULES.md: at most two joker cards in any meld
WRONG_DECLARE_PENALTY = 20   # RULES.md: cap points added per wrong declaration
_SEARCH_BUDGET = 60_000      # deterministic bound on declaration-search work

# Ace plays low (A-2-3) and high (Q-K-A); K-A-2 wraps and is never a run.
_LOW_POS = {rank: index for index, rank in enumerate(RANKS)}
_HIGH_POS = {rank: (index - 1) % 13 for index, rank in enumerate(RANKS)}


def sort_key(card: str) -> tuple[int, int]:
    """Contract card order, with the printed jokers sorting after every natural."""
    if card in JOKER_CARDS:
        return (len(RANKS), 0)
    return (RANKS.index(card[0]), SUITS.index(card[1]))


def is_joker(card: str, wild_rank: str) -> bool:
    """Printed jokers and every suit of the public wild rank act as jokers."""
    return card in JOKER_CARDS or card[0] == wild_rank


def card_points(card: str, wild_rank: str) -> int:
    """Indian Rummy points: jokers 0, A/K/Q/J/T 10, number cards face value."""
    if is_joker(card, wild_rank):
        return 0
    return 10 if card[0] in "TJQKA" else int(card[0])


def classify_meld(group: list[str], wild_rank: str) -> str | None:
    """Return 'pure', 'impure', or 'set' for a legal meld, else None.

    Exactly the RULES.md meld definitions: sequences run within one suit
    (ace low or high, never wrapping), sets hold 3–4 cards of one rank with
    distinct natural suits, at most two joker cards join any meld, an
    all-joker group anchors nothing, and no card ID repeats inside a meld.
    """
    if type(group) is not list or len(group) < 3 or len(set(group)) != len(group):
        return None
    naturals = [card for card in group if not is_joker(card, wild_rank)]
    jokers = len(group) - len(naturals)
    if not naturals or jokers > JOKERS_PER_MELD:
        return None
    natural_ranks = {card[0] for card in naturals}
    if len(natural_ranks) == 1:
        # A set: 3–4 cards of one rank, at most one card per suit.
        if len(group) <= 4 and len({card[1] for card in naturals}) == len(naturals):
            return "set"
        return None
    if len({card[1] for card in naturals}) != 1:
        return None  # a sequence needs one suit
    if len(natural_ranks) != len(naturals):
        return None  # a repeated rank breaks the run (two decks allow copies)
    size = len(group)
    for positions in (_LOW_POS, _HIGH_POS):
        ordered = sorted(natural_ranks, key=positions.__getitem__)
        if positions[ordered[-1]] - positions[ordered[0]] + 1 <= size:
            return "impure" if jokers else "pure"
    return None


def _sequence_melds(
    base: list[str],
    ranks: list[str],
    rank_map: dict[str, str],
    joker_pool: list[str],
    min_jokers: int,
    budget: list[int],
) -> list[list[str]]:
    """Sequence melds: `base` naturals plus a subset of `ranks`, gaps filled
    by jokers. `base` carries the anchor card so every meld contains it."""
    out: list[list[str]] = []
    base_ranks = {card[0] for card in base}
    extra = [rank for rank in ranks if rank not in base_ranks]
    for count in range(len(extra) + 1):
        for combo in combinations(extra, count):
            chosen = base + [rank_map[rank] for rank in combo]
            if not chosen:
                continue  # a meld anchors on at least one natural card
            size = len(chosen)
            all_ranks = base_ranks | set(combo)
            span = min(
                max(pos[rank] for rank in all_ranks)
                - min(pos[rank] for rank in all_ranks) + 1
                for pos in (_LOW_POS, _HIGH_POS)
            )
            j_min = max(min_jokers, 3 - size, span - size)
            j_max = min(JOKERS_PER_MELD, len(joker_pool))
            for j in range(j_min, j_max + 1):
                if budget[0] <= 0:
                    return out
                budget[0] -= 1
                out.append(chosen + joker_pool[:j])
    return out


def _set_melds(
    base: list[str],
    extras: list[str],
    joker_pool: list[str],
    min_jokers: int,
    budget: list[int],
) -> list[list[str]]:
    """Set melds: 3–4 cards of one rank, at most one card per suit."""
    out: list[list[str]] = []
    for count in range(len(extras) + 1):
        for combo in combinations(extras, count):
            chosen = base + list(combo)
            if not chosen:
                continue  # an all-joker set anchors on nothing
            size = len(chosen)
            j_min = max(min_jokers, 3 - size)
            j_max = min(JOKERS_PER_MELD, 4 - size, len(joker_pool))
            for j in range(j_min, j_max + 1):
                if budget[0] <= 0:
                    return out
                budget[0] -= 1
                out.append(chosen + joker_pool[:j])
    return out


def _meld_candidates(
    anchor: str, cards: list[str], wild_rank: str, budget: list[int]
) -> list[list[str]]:
    """Every valid meld built from `cards` that contains `anchor`, in a
    fixed deterministic order (sequences before sets, small melds first)."""
    pool = sorted(
        (card for card in cards if is_joker(card, wild_rank)),
        key=lambda card: (card != anchor, card),
    )
    naturals_by_suit: dict[str, dict[str, str]] = {}
    for card in cards:
        if not is_joker(card, wild_rank):
            naturals_by_suit.setdefault(card[1], {}).setdefault(card[0], card)

    seen: set[tuple[str, ...]] = set()
    out: list[list[str]] = []

    def offer(meld: list[str]) -> None:
        key = tuple(meld)
        if key not in seen:
            seen.add(key)
            out.append(meld)

    if is_joker(anchor, wild_rank):
        # A joker anchor joins any suit's run or any rank's set as a spare card.
        for suit in sorted(naturals_by_suit):
            rank_map = naturals_by_suit[suit]
            ranks = sorted(rank_map, key=_LOW_POS.__getitem__)
            for meld in _sequence_melds([], ranks, rank_map, pool, 1, budget):
                offer(meld)
        by_rank: dict[str, list[str]] = {}
        for suit in sorted(naturals_by_suit):
            for rank, card in naturals_by_suit[suit].items():
                by_rank.setdefault(rank, []).append(card)
        for rank in sorted(by_rank, key=_LOW_POS.__getitem__):
            for meld in _set_melds([], sorted(by_rank[rank]), pool, 1, budget):
                offer(meld)
    else:
        rank_map = naturals_by_suit.get(anchor[1], {})
        ranks = sorted(rank_map, key=_LOW_POS.__getitem__)
        for meld in _sequence_melds([anchor], ranks, rank_map, pool, 0, budget):
            offer(meld)
        mates = [
            naturals_by_suit[suit][anchor[0]]
            for suit in sorted(naturals_by_suit)
            if anchor[0] in naturals_by_suit[suit]
        ]
        for meld in _set_melds([anchor], [m for m in mates if m != anchor], pool, 0, budget):
            offer(meld)
    return out


def _hand_key(card: str, wild_rank: str) -> tuple:
    """Deterministic card order: naturals by contract key, jokers last."""
    if is_joker(card, wild_rank):
        return (1, 99, card)
    return (0, RANKS.index(card[0]), SUITS.index(card[1]))


def _without(cards: list[str], meld: list[str]) -> list[str]:
    rest = list(cards)
    for card in meld:
        rest.remove(card)
    return rest


def find_groups(
    cards: list[str], wild_rank: str, require_declaration: bool = False
) -> list[list[str]] | None:
    """Deterministic bounded search for a full meld partition of `cards`.

    With `require_declaration` the partition must also satisfy the RULES.md
    declaration shape: at least two sequences, one of them pure. Returns
    the groups, or None when the budget found nothing (a documented
    bounded-search answer, always identical for identical inputs).
    """
    remaining = sorted(cards, key=lambda card: _hand_key(card, wild_rank))
    budget = [_SEARCH_BUDGET]

    def meets(groups: list[list[str]]) -> bool:
        kinds = [classify_meld(group, wild_rank) for group in groups]
        sequences = [kind for kind in kinds if kind in ("pure", "impure")]
        return len(sequences) >= 2 and "pure" in kinds

    def search(rest: list[str], acc: list[list[str]]) -> list[list[str]] | None:
        if not rest:
            return list(acc) if not require_declaration or meets(acc) else None
        if budget[0] <= 0:
            return None
        budget[0] -= 1
        for meld in _meld_candidates(rest[0], rest, wild_rank, budget):
            tail = search(_without(rest, meld), acc + [meld])
            if tail is not None:
                return tail
        return None

    return search(remaining, [])


def valid_declaration(cards: list[str], wild_rank: str) -> list[list[str]] | None:
    """Groups when `cards` form a legal declaration shape, else None."""
    return find_groups(cards, wild_rank, require_declaration=True)


def hand_deadwood(cards: list[str], wild_rank: str) -> int:
    """RULES.md cap scoring: a fully declarable hand scores zero, any other
    hand scores the full point value of all its cards."""
    if valid_declaration(cards, wild_rank) is not None:
        return 0
    return sum(card_points(card, wild_rank) for card in cards)


def _validate_draw(raw) -> dict | None:
    if type(raw) is not dict or raw.get("type") != "draw":
        return None
    source = raw.get("from")
    if source not in ("stock", "discard"):
        return None
    return {"type": "draw", "from": source}


def _validate_discard(raw, hand: Hand) -> dict | None:
    if type(raw) is not dict or raw.get("type") != "discard":
        return None
    card = raw.get("card")
    if type(card) is not str or card not in hand:
        return None
    return {"type": "discard", "card": card}


def _validate_declare(raw, hand: Hand) -> dict | None:
    """`pass` passes; a show naming exactly the owned 14 cards is a declare.

    Anything else — wrong types, wrong counts, cards the seat does not
    hold — is an invalid action (plain fault), not a wrong declaration.
    """
    if type(raw) is not dict:
        return None
    kind = raw.get("type")
    if kind == "pass":
        return {"type": "pass"}
    if kind != "declare":
        return None
    shown = raw.get("hand")
    if (
        type(shown) is not list
        or len(shown) != HAND_SIZE + 1
        or not all(type(card) is str for card in shown)
    ):
        return None
    if sorted(shown) != sorted(hand.to_list()):
        return None
    return {"type": "declare", "hand": list(shown)}


def play_rummy_match(
    bots: list,
    seed: int,
    decision_cap: int = DECISION_CAP,
    capture: bool = False,
) -> dict:
    n = len(bots)
    if n not in SEATS:
        raise ValueError("Rummy v1 is played with 2 to 6 seats.")
    if not 1 <= decision_cap <= 100_000:
        raise ValueError("decision_cap must be between 1 and 100000.")

    rng = random.Random(seed)
    shoe = Deck(standard_deck() * 2 + list(JOKER_CARDS), seed)
    shoe.shuffle()
    stock = shoe.draw(shoe.remaining)  # top-first; the shared engine shuffles
    hands: list[Hand] = []
    for _ in range(n):
        hands.append(Hand(stock[:HAND_SIZE], key=sort_key))
        del stock[:HAND_SIZE]

    # The public wild rank: flip stock cards until a natural appears; flipped
    # printed jokers return to the bottom of the stock (RULES.md deviation 5).
    wild_rank = None
    while wild_rank is None:
        card = stock.pop(0)
        if card[0] in RANKS:
            wild_rank = card[0]
        stock.append(card)
    discard_pile = [stock.pop(0)]

    faults = [0] * n
    errors: list[str | None] = [None] * n
    reset_failed = [False] * n
    for seat, bot in enumerate(bots):
        try:
            bot.reset()
        except SandboxDown:
            raise
        except Exception as exc:  # noqa: BLE001 - timeout, crash, or invalid reply
            faults[seat] += 1
            errors[seat] = str(exc)[:200]
            reset_failed[seat] = True

    decision_number = 0
    history: list[dict] = []
    log: list[dict] = []
    frames: list[dict] = []
    wrong_shows = [0] * n
    winner_seats: list[int] | None = None
    terminal: str | None = None

    log.append({
        "type": "deal",
        "hands": [hand.to_list() for hand in hands],
        "stock": list(stock),
        "discard": list(discard_pile),
        "wild_rank": wild_rank,
    })

    def names() -> list[str]:
        return [str(getattr(bot, "name", f"Seat {i + 1}")) for i, bot in enumerate(bots)]

    def counts() -> list[int]:
        return [len(hand) for hand in hands]

    def frame(kind: str, **fields) -> None:
        if capture:
            frames.append({
                "kind": kind,
                "counts": counts(),
                "stock_remaining": len(stock),
                "discard_size": len(discard_pile),
                **fields,
            })

    def observe(seat: int, turn: dict) -> dict:
        """The frozen visibility table: own hand, public counts and edges,
        public history — never the stock order or another seat's cards."""
        return {
            "protocol": PROTOCOL,
            "game": GAME_ID,
            "rules_version": RULES_VERSION,
            "seat": seat,
            "players": [
                {"seat": i, "name": names()[i], "count": len(hands[i])}
                for i in range(n)
            ],
            "hand": hands[seat].to_list(),
            "wild_rank": wild_rank,
            "stock_remaining": len(stock),
            "discard_top": discard_pile[-1] if discard_pile else None,
            "discard_size": len(discard_pile),
            "turn": turn,
            "history": [dict(event) for event in history],
            "decision_number": decision_number + 1,
            "decision_cap": decision_cap,
        }

    def decide(seat: int, turn: dict, fallback: dict, validate) -> tuple[dict, bool]:
        """Collect one decision; faults fall back deterministically."""
        nonlocal decision_number
        decision_number += 1
        if reset_failed[seat]:
            return dict(fallback), True
        try:
            raw = bots[seat].act(observe(seat, turn))
        except SandboxDown:
            raise
        except Exception as exc:  # noqa: BLE001 - timeout, crash, or invalid reply
            faults[seat] += 1
            if errors[seat] is None:
                errors[seat] = str(exc)[:200]
            return dict(fallback), True
        action = validate(raw)
        if action is None:
            faults[seat] += 1
            if errors[seat] is None:
                errors[seat] = f"invalid {turn['type']} action"
            return dict(fallback), True
        return action, False

    active = 0
    while winner_seats is None:
        # The cap cuts at a 13-card turn boundary (RULES.md deviation 10).
        if decision_number >= decision_cap:
            terminal = "cap"
            break
        seat = active
        hand = hands[seat]

        # -- draw ---------------------------------------------------------
        action, _ = decide(
            seat, {"type": "draw"}, {"type": "draw", "from": "stock"}, _validate_draw,
        )
        source = action["from"]
        if source == "discard" and not discard_pile:
            faults[seat] += 1
            if errors[seat] is None:
                errors[seat] = "discard pile is empty"
            source = "stock"
        if source == "stock" and not stock:
            moved = discard_pile[:-1]  # the public top card stays put
            if moved:
                rng.shuffle(moved)
                stock = moved
                del discard_pile[:-1]
                history.append({"type": "reshuffle", "moved": len(moved)})
                log.append({
                    "type": "reshuffle", "moved": list(moved), "stock": list(stock),
                })
                frame("reshuffle", moved=len(moved))
        if source == "stock" and not stock:
            faults[seat] += 1
            if errors[seat] is None:
                errors[seat] = "stock is empty"
            source = "discard" if discard_pile else None
        card = None
        if source == "discard" and discard_pile:
            card = discard_pile.pop()
        elif source == "stock" and stock:
            card = stock.pop(0)
        if card is not None:
            hand.add(card)
        history.append({
            "type": "draw", "seat": seat, "from": source,
            "card": card if source == "discard" else None,
        })
        log.append({
            "type": "draw", "seat": seat, "from": source, "card": card,
            "hand_after": hand.to_list(), "stock": list(stock),
            "discard": list(discard_pile),
        })
        frame("draw", seat=seat, **{
            "from": source, "card": card if source == "discard" else None,
        })

        # -- optional declaration (only at 14 cards) -----------------------
        if len(hand) == HAND_SIZE + 1:
            action, _ = decide(
                seat, {"type": "declare"}, {"type": "pass"},
                lambda raw, held=hand: _validate_declare(raw, held),
            )
            if action["type"] == "declare":
                shown = action["hand"]
                groups = valid_declaration(shown, wild_rank)
                if groups is not None:
                    history.append({
                        "type": "declaration", "seat": seat,
                        "hand": list(shown), "groups": groups,
                    })
                    log.append({
                        "type": "declaration", "seat": seat,
                        "hand": list(shown), "groups": groups,
                    })
                    frame("declaration", seat=seat, hand=list(shown), groups=groups)
                    winner_seats = [seat]
                    terminal = "win"
                    break
                # Wrong show: fault, cap penalty, and a public reveal.
                wrong_shows[seat] += 1
                faults[seat] += 1
                if errors[seat] is None:
                    errors[seat] = "wrong declaration"
                history.append({
                    "type": "wrong_declaration", "seat": seat, "hand": list(shown),
                })
                log.append({
                    "type": "wrong_declaration", "seat": seat, "hand": list(shown),
                    "penalty": WRONG_DECLARE_PENALTY,
                })
                frame("wrong_declaration", seat=seat, hand=list(shown))

        # -- mandatory discard ---------------------------------------------
        lowest = min(hand.to_list(), key=sort_key)
        action, _ = decide(
            seat, {"type": "discard"}, {"type": "discard", "card": lowest},
            lambda raw, held=hand: _validate_discard(raw, held),
        )
        card = action["card"]
        hand.remove(card)
        discard_pile.append(card)
        history.append({"type": "discard", "seat": seat, "card": card})
        log.append({
            "type": "discard", "seat": seat, "card": card,
            "hand_after": hand.to_list(),
        })
        frame("discard", seat=seat, card=card)
        active = (seat + 1) % n

    deadwood = [
        hand_deadwood(hands[i].to_list(), wild_rank) + WRONG_DECLARE_PENALTY * wrong_shows[i]
        for i in range(n)
    ]
    if terminal == "cap":
        lowest = min(deadwood)
        winner_seats = [i for i in range(n) if deadwood[i] == lowest]
    frame("end", reason=terminal, winner_seats=winner_seats)
    log.append({
        "type": "end", "reason": terminal, "winner_seats": winner_seats,
        "hands": [hand.to_list() for hand in hands],
        "stock": list(stock), "discard": list(discard_pile),
        "deadwood": deadwood, "wrong_shows": wrong_shows, "wild_rank": wild_rank,
    })
    share = 1.0 / len(winner_seats)
    points = [share if i in winner_seats else 0.0 for i in range(n)]
    return {
        "points": points,
        "winner_seats": winner_seats,
        "terminal_reason": terminal,
        "faults": faults,
        "errors": errors,
        "hands": 1,
        "matches": 1,
        "decisions": decision_number,
        "names": names(),
        "log": log,
        "frames": {
            "game": GAME_ID, "protocol": PROTOCOL, "names": names(), "frames": frames,
        },
    }
