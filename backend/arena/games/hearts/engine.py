"""Stack Theory Hearts v1 — deterministic four-seat trick-avoidance engine.

Classic Hearts written to the frozen contract in `GAMES_CONTRACT.md` §11;
`RULES.md` (Hoyle citation + explicit deviation list) is the authoritative
rules text and was frozen before this code. Deterministic given (bots, seed):
the private deck is shuffled and dealt once through `arena.games.common.deck`,
and every agent decision either succeeds or falls back along a fixed rule
(pass the 3 lowest; play the lowest legal card). Hidden state — opponent
hands, the simultaneous pass submissions before their reveal — never enters an
observation or a public replay frame.
"""
from __future__ import annotations

from ...sandbox import SandboxDown
from ..common.deck import Deck, standard_deck

PROTOCOL = 1
GAME_ID = "hearts"
RULES_VERSION = 1
SEATS = 4
HAND_SIZE = 13
TRICK_COUNT = 13
PASS_SIZE = 3
DECISION_CAP = 500
HEART_POINTS = 1
QUEEN_POINTS = 13
MOON_POINTS = 26
RANKS = "A23456789TJQK"  # contract rank order (tidy hands); trick strength below
SUITS = "cdhs"
TWO_CLUBS = "2c"
QUEEN_SPADES = "Qs"
# Trick strength per RULES.md: 2 is lowest through ace highest.
STRENGTH = {rank: index for index, rank in enumerate("23456789TJQKA")}


def sort_key(card: str) -> tuple[int, int]:
    """Contract hand ordering (rank-major, suit-minor) for tidy stored hands."""
    return (RANKS.index(card[0]), SUITS.index(card[1]))


def low_key(card: str) -> tuple[int, int]:
    """Trick-strength ordering (2 low, ace high; c < d < h < s) per RULES.md C4."""
    return (STRENGTH[card[0]], SUITS.index(card[1]))


def points_of(card: str) -> int:
    """Penalty points carried by a single card."""
    if card[1] == "h":
        return HEART_POINTS
    if card == QUEEN_SPADES:
        return QUEEN_POINTS
    return 0


def trick_points(cards) -> int:
    """Penalty points carried by the cards of one trick."""
    return sum(points_of(card) for card in cards)


def score_hand(taken: list[int]) -> list[int]:
    """Final penalty points per seat, applying the shoot-the-moon payout."""
    shooter = next((seat for seat, points in enumerate(taken) if points == MOON_POINTS), None)
    if shooter is None:
        return list(taken)
    return [0 if seat == shooter else MOON_POINTS for seat in range(len(taken))]


def legal_plays(hand, trick_cards, hearts_broken, trick_number) -> list[str]:
    """Cards the seat may legally play now, per RULES.md "The tricks"."""
    if not trick_cards:  # this seat leads
        if trick_number == 0:
            return [TWO_CLUBS] if TWO_CLUBS in hand else []  # C2: the 2♣ opens, compulsory
        if hearts_broken:
            return list(hand)
        plain = [card for card in hand if card[1] != "h"]
        return plain or list(hand)  # C3: an all-hearts hand may lead a heart
    led_suit = trick_cards[0][1]
    follow = [card for card in hand if card[1] == led_suit]
    return follow or list(hand)  # void in the led suit: any card (D3 included)


def fallback_pass(hand) -> list[str]:
    """Fault fallback for the pass phase: the three lowest cards (RULES.md C4)."""
    return sorted(hand, key=low_key)[:PASS_SIZE]


def fallback_play(hand, trick_cards, hearts_broken, trick_number) -> str:
    """Fault fallback for tricks: the lowest legal card (RULES.md C4)."""
    return min(legal_plays(hand, trick_cards, hearts_broken, trick_number), key=low_key)


def _validate_pass(raw, hand) -> list[str] | None:
    """Return the passed cards if the action is legal, else None."""
    if type(raw) is not list or len(raw) != PASS_SIZE:
        return None
    remaining = list(hand)
    for card in raw:
        if type(card) is not str or card not in remaining:
            return None
        remaining.remove(card)
    return list(raw)


def _validate_play(raw, hand, trick_cards, hearts_broken, trick_number) -> str | None:
    """Return the card if the action is a legal play, else None."""
    if type(raw) is not dict:
        return None
    card = raw.get("card")
    if type(card) is not str or card not in hand:
        return None
    if card not in legal_plays(hand, trick_cards, hearts_broken, trick_number):
        return None
    return card


def play_hearts_match(
    bots: list,
    seed: int,
    decision_cap: int = DECISION_CAP,
    capture: bool = False,
) -> dict:
    """Run one 13-trick Hearts match; deterministic given (bots, seed)."""
    if len(bots) != SEATS:
        raise ValueError(f"Hearts v1 is played with exactly {SEATS} seats.")
    if not 1 <= decision_cap <= 100_000:
        raise ValueError("decision_cap must be between 1 and 100000.")

    deck = Deck(standard_deck(), seed=seed)
    deck.shuffle()
    hands = [hand.to_list() for hand in deck.deal(SEATS)]  # 13 x 4, contract-sorted

    received: list[list[str] | None] = [None] * SEATS
    trick: list[tuple[int, str]] = []   # plays to the current trick, in order
    tricks: list[dict] = []             # completed tricks, fully public
    hearts_broken = False
    leader: int | None = None           # seat on lead for the upcoming trick
    taken = [0] * SEATS
    faults = [0] * SEATS
    errors: list[str | None] = [None] * SEATS
    reset_failed = [False] * SEATS
    for seat, bot in enumerate(bots):
        try:
            bot.reset()
        except SandboxDown:
            raise
        except Exception as exc:  # noqa: BLE001 - any bot failure is a fault, not a crash
            faults[seat] += 1
            errors[seat] = str(exc)[:200]
            reset_failed[seat] = True
    decision_number = 0
    frames: list[dict] = []
    log: list[dict] = [{"type": "deal", "hands": [sorted(hand, key=sort_key) for hand in hands]}]
    terminal: str | None = None

    def names() -> list[str]:
        return [str(getattr(bot, "name", f"Seat {i + 1}")) for i, bot in enumerate(bots)]

    def counts() -> list[int]:
        return [len(hand) for hand in hands]

    def frame(kind: str, **fields) -> None:
        if capture:
            frames.append({"kind": kind, "counts": counts(), **fields})

    def observation(seat: int, turn: dict) -> dict:
        players = [
            {"seat": i, "name": names()[i], "count": len(hands[i]), "taken": taken[i]}
            for i in range(SEATS)
        ]
        return {
            "protocol": PROTOCOL,
            "game": GAME_ID,
            "rules_version": RULES_VERSION,
            "seat": seat,
            "players": players,
            "hand": list(hands[seat]),
            # Passed cards are revealed to the receiver only (contract §11):
            # None until the simultaneous pass resolves, then permanent
            # private knowledge of this seat.
            "received": list(received[seat]) if received[seat] is not None else None,
            "pass_direction": "left",
            "trick_number": len(tricks),
            "leader": leader,
            "trick": [{"seat": s, "card": c} for s, c in trick],
            "hearts_broken": hearts_broken,
            "tricks": [dict(event) for event in tricks],
            "turn": turn,
            "decision_number": decision_number + 1,
            "decision_cap": decision_cap,
        }

    def decide(seat: int, turn: dict, fallback) -> tuple[object, bool]:
        """Collect one decision; faults fall back deterministically."""
        nonlocal decision_number
        decision_number += 1
        if reset_failed[seat]:
            return fallback, True
        try:
            raw = bots[seat].act(observation(seat, turn))
        except SandboxDown:
            raise
        except Exception as exc:  # noqa: BLE001 - any bot failure is a fault, not a crash
            faults[seat] += 1
            if errors[seat] is None:
                errors[seat] = str(exc)[:200]
            return fallback, True
        if turn["type"] == "pass":
            cards = _validate_pass(raw.get("cards") if type(raw) is dict else None, hands[seat])
            if cards is None:
                faults[seat] += 1
                if errors[seat] is None:
                    errors[seat] = "invalid pass action"
                return fallback, True
            return cards, False
        trick_cards = [played for _, played in trick]
        card = _validate_play(raw, hands[seat], trick_cards, hearts_broken, len(tricks))
        if card is None:
            faults[seat] += 1
            if errors[seat] is None:
                errors[seat] = "invalid play action"
            return fallback_play(hands[seat], trick_cards, hearts_broken, len(tricks)), True
        return card, False

    # Pass phase: all four seats submit 3 cards simultaneously (contract §11).
    # Submissions are collected from the untouched hands first; only then are
    # they removed, delivered, and revealed to each receiver.
    submissions: list[list[str]] = []
    for seat in range(SEATS):
        action, faulted = decide(seat, {"type": "pass"}, fallback_pass(hands[seat]))
        submissions.append(list(action))
        log.append({"type": "pass", "seat": seat, "cards": list(action),
                    "to": (seat + 1) % SEATS, "fault": faulted})
    for seat in range(SEATS):
        for card in submissions[seat]:
            hands[seat].remove(card)
    for seat in range(SEATS):
        receiver = (seat + 1) % SEATS  # single match: pass left (RULES.md D2)
        hands[receiver].extend(submissions[seat])
        hands[receiver].sort(key=sort_key)
        received[receiver] = list(submissions[seat])
        frame("pass", seat=seat)
    leader = next(seat for seat in range(SEATS) if TWO_CLUBS in hands[seat])
    log.append({"type": "reveal", "hands": [sorted(hand, key=sort_key) for hand in hands],
                "leader": leader})

    # Trick phase: 13 tricks, the winner of each leading the next.
    for trick_index in range(TRICK_COUNT):
        if decision_number >= decision_cap:  # safety net; unreachable on the rules path
            terminal = "cap"
            break
        trick = []
        for offset in range(SEATS):
            seat = (leader + offset) % SEATS
            trick_cards = [played for _, played in trick]
            action, faulted = decide(
                seat, {"type": "play"},
                fallback_play(hands[seat], trick_cards, hearts_broken, trick_index),
            )
            card = action
            hands[seat].remove(card)
            if card[1] == "h" and not hearts_broken:
                hearts_broken = True  # any heart played breaks hearts (RULES.md)
            trick.append((seat, card))
            log.append({"type": "play", "seat": seat, "card": card, "trick": trick_index,
                        "fault": faulted, "hearts_broken": hearts_broken})
            frame("play", seat=seat, card=card, trick=trick_index)
        led_suit = trick[0][1][1]
        winning_seat, winning_card = trick[0]
        for seat, card in trick[1:]:
            if card[1] == led_suit and STRENGTH[card[0]] > STRENGTH[winning_card[0]]:
                winning_seat, winning_card = seat, card
        penalty = trick_points(played for _, played in trick)
        taken[winning_seat] += penalty
        plays = [{"seat": s, "card": c} for s, c in trick]
        tricks.append({"trick": trick_index, "winner": winning_seat,
                       "points": penalty, "cards": plays})
        log.append({"type": "trick", "trick": trick_index, "winner": winning_seat,
                    "points": penalty, "led_suit": led_suit,
                    "cards": [[s, c] for s, c in trick]})
        frame("trick", trick=trick_index, winner=winning_seat, points=penalty,
              cards=plays, hearts_broken=hearts_broken)
        leader = winning_seat
        trick = []

    if terminal is None:
        terminal = "win"
    final_points = score_hand(taken)
    fewest = min(final_points)
    winner_seats = [seat for seat in range(SEATS) if final_points[seat] == fewest]
    frame("end", reason=terminal, winner_seats=winner_seats, points=final_points)
    log.append({"type": "end", "reason": terminal, "winner_seats": winner_seats,
                "points": final_points, "penalties": list(taken),
                "hands": [sorted(hand, key=sort_key) for hand in hands]})
    share = 1.0 / len(winner_seats)
    match_points = [share if seat in winner_seats else 0.0 for seat in range(SEATS)]
    return {
        "points": final_points,
        "match_points": match_points,
        "winner_seats": winner_seats,
        "terminal_reason": terminal,
        "faults": faults,
        "errors": errors,
        "hands": 1,
        "matches": 1,
        "decisions": decision_number,
        "names": names(),
        "log": log,
        "frames": frames,
    }
