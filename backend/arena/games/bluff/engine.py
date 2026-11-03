"""Stack Theory Bluff v1 — deterministic four-seat engine.

A selected variant of the classic Cheat / I Doubt It party game, written to
the frozen contract in `GAMES_CONTRACT.md` (observations/actions/result/
replay). Deterministic given (bots, seed): the private deck is shuffled once
with the seed, and every agent decision either succeeds or falls back along a
fixed rule. Hidden state — opponent hands, deck order, the face-down pile,
and future decisions — never enters an observation or a public replay frame.
"""
from __future__ import annotations

import random

from ...sandbox import SandboxDown

PROTOCOL = 1
GAME_ID = "bluff"
RULES_VERSION = 1
SEATS = 4
RANKS = "A23456789TJQK"  # required-rank cycle: A -> 2 -> ... -> K -> A
SUITS = "cdhs"
DECISION_CAP = 500
MAX_PLAY = 4


def sort_key(card: str) -> tuple[int, int]:
    """Stable hand ordering used for fallbacks and tidy hands."""
    return (RANKS.index(card[0]), SUITS.index(card[1]))


def _validate_cards(raw, hand: list[str]) -> list[str] | None:
    """Return the played cards if the action is legal, else None."""
    if type(raw) is not list or not 1 <= len(raw) <= MAX_PLAY:
        return None
    remaining = list(hand)
    for card in raw:
        if type(card) is not str or card not in remaining:
            return None
        remaining.remove(card)
    return list(raw)


def play_bluff_match(
    bots: list,
    seed: int,
    decision_cap: int = DECISION_CAP,
    capture: bool = False,
) -> dict:
    n = len(bots)
    if n != SEATS:
        raise ValueError(f"Bluff v1 is played with exactly {SEATS} seats.")
    if not 1 <= decision_cap <= 100_000:
        raise ValueError("decision_cap must be between 1 and 100000.")

    rng = random.Random(seed)
    deck = [rank + suit for rank in RANKS for suit in SUITS]
    rng.shuffle(deck)
    hands = [sorted(deck[seat::SEATS], key=sort_key) for seat in range(SEATS)]

    pile: list[str] = []
    history: list[dict] = []       # resolved public events
    pending: list[dict] = []       # in-progress challenge decisions
    batch: list[str] = []          # cards in the latest face-down claim
    declared_rank_index = 0
    rank_index = 0                 # required-rank cycle position
    active = 0
    phase = "play"                 # 'play' or 'challenge'
    claimant: int | None = None
    decider: int | None = None
    faults = [0] * SEATS
    errors: list[str | None] = [None] * SEATS
    reset_failed = [False] * SEATS
    for seat, bot in enumerate(bots):
        try:
            bot.reset()
        except SandboxDown:
            raise
        except Exception as exc:
            faults[seat] += 1
            errors[seat] = str(exc)[:200]
            reset_failed[seat] = True
    decision_number = 0
    frames: list[dict] = []
    log: list[dict] = []
    winner_seats: list[int] | None = None
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
            {"seat": i, "name": names()[i], "count": len(hands[i]), "out": len(hands[i]) == 0}
            for i in range(SEATS)
        ]
        return {
            "protocol": PROTOCOL,
            "game": GAME_ID,
            "rules_version": RULES_VERSION,
            "seat": seat,
            "players": players,
            "hand": list(hands[seat]),
            "required_rank": RANKS[rank_index],
            "pile_size": len(pile),
            "turn": turn,
            # A decider sees resolved events plus only the challenge decisions
            # made before their own; never the pending one or later ones.
            "history": [dict(event) for event in history] + [dict(event) for event in pending],
            "decision_number": decision_number + 1,
            "decision_cap": decision_cap,
        }

    def decide(seat: int, turn: dict, fallback: dict) -> tuple[dict, bool]:
        """Collect one decision; faults fall back deterministically."""
        nonlocal decision_number
        decision_number += 1
        if reset_failed[seat]:
            return dict(fallback), True
        try:
            raw = bots[seat].act(observation(seat, turn))
        except SandboxDown:
            raise
        except Exception as exc:  # timeout, crash, or invalid transport reply
            faults[seat] += 1
            if errors[seat] is None:
                errors[seat] = str(exc)[:200]
            return dict(fallback), True
        action = raw if type(raw) is dict else None
        if turn["type"] == "play":
            cards = None
            if action is not None and action.get("type") == "play":
                cards = _validate_cards(action.get("cards"), hands[seat])
            if not cards:
                faults[seat] += 1
                if errors[seat] is None:
                    errors[seat] = "invalid play action"
                return {"type": "play", "cards": [hands[seat][0]]}, True
            return {"type": "play", "cards": cards}, False
        kind = action.get("type") if action else None
        if kind not in ("challenge", "pass"):
            faults[seat] += 1
            if errors[seat] is None:
                errors[seat] = "invalid challenge decision"
            return {"type": "pass"}, True
        return {"type": kind}, False

    def resolve(challenger: int | None) -> None:
        """Settle the batch: pickup, rank advance, next active, win check."""
        nonlocal pile, batch, rank_index, active, phase, claimant, pending
        nonlocal winner_seats, terminal, declared_rank_index
        honest = None
        revealed = None
        taken_by = None
        if challenger is not None:
            honest = all(card[0] == RANKS[declared_rank_index] for card in batch)
            taken_by = claimant if not honest else challenger
            revealed = list(batch)
        pile_before = list(pile)
        if taken_by is not None:
            hands[taken_by].extend(pile)
            hands[taken_by].sort(key=sort_key)
            pile = []
        # A player who emptied their hand wins only now — after every
        # challenge decision resolved — and only if the hand is still empty.
        empties = [i for i in range(SEATS) if not hands[i]]
        next_rank = RANKS[(rank_index + 1) % len(RANKS)]
        event = {
            "type": "resolution", "claimant": claimant,
            "challenged_by": challenger, "revealed": revealed, "honest": honest,
            "taken_by": taken_by, "next_rank": next_rank,
        }
        if empties:
            event["winner_seats"] = list(empties)
        history.append(event)
        log.append({"type": "resolution", "claimant": claimant,
                    "challenged_by": challenger, "batch": list(batch),
                    "revealed": revealed, "pile": pile_before,
                    "honest": honest, "taken_by": taken_by})
        frame("resolution", claimant=claimant, challenged_by=challenger,
              revealed=revealed, honest=honest, taken_by=taken_by,
              pile_size=len(pile), next_rank=next_rank)
        rank_index = (rank_index + 1) % len(RANKS)
        active = (claimant + 1) % SEATS
        batch = []
        pending = []
        claimant = None
        phase = "play"
        if empties:
            winner_seats = empties
            terminal = "win"

    while winner_seats is None:
        # Finish the current challenge sequence before applying the cap.
        if decision_number >= decision_cap and phase == "play":
            terminal = "cap"
            break
        if phase == "play":
            seat = active
            action, faulted = decide(
                seat, {"type": "play"},
                {"type": "play", "cards": [hands[seat][0]]},
            )
            cards = action["cards"]
            for card in cards:
                hands[seat].remove(card)
            pile.extend(cards)
            batch = list(cards)
            declared_rank_index = rank_index
            claimant = seat
            pending = []
            event = {"type": "play", "seat": seat, "rank": RANKS[rank_index],
                     "count": len(cards), "pile_size": len(pile)}
            history.append(event)
            log.append({"type": "play", "seat": seat, "cards": list(cards),
                        "declared_rank": RANKS[rank_index], "fault": faulted})
            frame("play", seat=seat, rank=RANKS[rank_index], count=len(cards),
                  pile_size=len(pile))
            decider = (seat + 1) % SEATS
            phase = "challenge"
            continue
        # Challenge phase: every other player decides clockwise; the first
        # challenge stops the sequence.
        if decider == claimant:
            raise RuntimeError("challenge sequence reached the claimant")
        action, faulted = decide(
            decider,
            {"type": "challenge", "claimant": claimant,
             "rank": RANKS[declared_rank_index], "count": len(batch)},
            {"type": "pass"},
        )
        kind = action["type"]
        pending.append({"type": kind, "seat": decider})
        log.append({"type": kind, "seat": decider, "fault": faulted})
        frame(kind, seat=decider, pile_size=len(pile))
        if kind == "challenge":
            resolve(challenger=decider)
        else:
            nxt = (decider + 1) % SEATS
            if nxt == claimant:
                resolve(challenger=None)
            else:
                decider = nxt

    if terminal == "cap":
        fewest = min(counts())
        winner_seats = [i for i in range(SEATS) if counts()[i] == fewest]
    frame("end", reason=terminal, winner_seats=winner_seats)
    log.append({"type": "end", "reason": terminal, "winner_seats": winner_seats,
                "hands": [sorted(hand, key=sort_key) for hand in hands],
                "pile": list(pile), "final_rank": RANKS[rank_index]})
    share = 1.0 / len(winner_seats)
    points = [share if i in winner_seats else 0.0 for i in range(SEATS)]
    return {
        "points": points,
        "winner_seats": winner_seats,
        "terminal_reason": terminal,
        "faults": faults,
        "errors": errors,
        "hands": 1,
        "matches": 1,
        "decisions": decision_number,
        "final_rank": RANKS[rank_index],
        "names": names(),
        "log": log,
        "frames": frames,
    }
