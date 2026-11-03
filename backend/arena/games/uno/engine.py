"""Stack Theory UNO v1 — deterministic two-to-four-seat engine.

Familiar UNO as an exact, cited rules prototype: `RULES.md` in this package
was written before this engine and is binding on it — the engine implements
that document, never the other way around. Deterministic given (bots, seed):
the private 108-card deck is built and shuffled once by the shared deck
engine, and every agent decision either succeeds or falls back along a fixed
rule. Hidden state — opponent hands and the draw-stack order — never enters
an observation or a public replay frame.
"""
from __future__ import annotations

from ...sandbox import SandboxDown
from ..common.deck import Deck, Hand

PROTOCOL = 1
GAME_ID = "uno"
RULES_VERSION = 1
DECISION_CAP = 500
COLORS = "rygb"
HAND_SIZE = 7
MIN_SEATS = 2
MAX_SEATS = 4
NUMBER_FACES = tuple(str(i) for i in range(10))
COLOR_ACTION_FACES = ("skip", "reverse", "draw2")
WILD_FACES = ("wild", "wild4")
FACE_ORDER = NUMBER_FACES + COLOR_ACTION_FACES + WILD_FACES
FACE_INDEX = {face: index for index, face in enumerate(FACE_ORDER)}


COLOR_ORDER = COLORS + "w"  # wilds sort after every color in tidy hands


def uno_deck() -> list[str]:
    """The 108-card deck under the RULES.md ID scheme (color + face + copy)."""
    cards = [f"{color}0a" for color in COLORS]
    for color in COLORS:
        for face in list(NUMBER_FACES[1:]) + list(COLOR_ACTION_FACES):
            cards.append(f"{color}{face}a")
            cards.append(f"{color}{face}b")
    cards.extend(f"wwild{letter}" for letter in "abcd")
    cards.extend(f"wwild4{letter}" for letter in "abcd")
    return cards


def card_color(card: str) -> str:
    return card[0]


def card_face(card: str) -> str:
    return card[1:-1]


def is_wild(card: str) -> bool:
    return card[0] == "w"


def sort_key(card: str) -> tuple[int, int, str]:
    """Stable hand ordering: color, face, copy letter (RULES.md section 3)."""
    return (COLOR_ORDER.index(card[0]), FACE_INDEX[card_face(card)], card[-1])


def matches(card: str, top: str, active_color: str) -> bool:
    """A card is playable on the discard top under the active color."""
    return is_wild(card) or card_color(card) == active_color or card_face(card) == card_face(top)


def play_uno_match(
    bots: list,
    seed: int,
    decision_cap: int = DECISION_CAP,
    capture: bool = False,
) -> dict:
    n = len(bots)
    if not MIN_SEATS <= n <= MAX_SEATS:
        raise ValueError(f"UNO v1 is played with {MIN_SEATS} to {MAX_SEATS} seats.")
    if not 1 <= decision_cap <= 100_000:
        raise ValueError("decision_cap must be between 1 and 100000.")

    deck = Deck(uno_deck(), seed)
    deck.shuffle()
    dealt = deck.draw(HAND_SIZE * n)
    hands = [Hand(dealt[seat::n], key=sort_key) for seat in range(n)]

    # Start-card flip: wilds go back to the bottom and are re-flipped (D9/D12).
    reflipped = 0
    while True:
        card = deck.draw(1)[0]
        if card_face(card) in WILD_FACES:
            deck.discard([card])
            reflipped += 1
            continue
        break
    discard: list[str] = [card]
    direction = 1
    color_state = card_color(card)
    start_face = card_face(card)
    pending = 0
    if start_face == "skip":
        active = 2 % n
    elif start_face == "reverse":
        if n == 2:
            active = 2 % n  # two-player reverse acts as a skip
        else:
            direction = -1
            active = (0 - 1) % n
    elif start_face == "draw2":
        active = 1 % n
        pending = 2
    else:
        active = 1 % n
    stage = "penalty" if pending else "play"
    direction_word = "cw" if direction == 1 else "ccw"

    names_list = [str(getattr(bot, "name", f"Seat {i + 1}")) for i, bot in enumerate(bots)]
    faults = [0] * n
    errors: list[str | None] = [None] * n
    reset_failed = [False] * n
    for seat, bot in enumerate(bots):
        try:
            bot.reset()
        except SandboxDown:
            raise
        except Exception as exc:  # noqa: BLE001 - bot faults must never abort the table
            faults[seat] += 1
            errors[seat] = str(exc)[:200]
            reset_failed[seat] = True
    decision_number = 0
    frames: list[dict] = []
    log: list[dict] = []
    declared: set[int] = set()
    drawn_card: str | None = None
    cont: tuple = ()  # after a UNO window: ("challenge",) or ("effects", face)
    wdf_player = -1
    wdf_card = ""
    wdf_color = ""
    wdf_legal = False
    wdf_last = False
    terminal: str | None = None
    winner_seats: list[int] | None = None
    final_action: dict | None = None

    def counts() -> list[int]:
        return [len(hand) for hand in hands]

    def frame(kind: str, **fields) -> None:
        if capture:
            frames.append({"kind": kind, "counts": counts(), **fields})

    log.append({"type": "start", "card": card, "color": color_state,
                "direction": direction_word, "active_seat": active, "reflipped": reflipped})
    frame("start", card=card, color=color_state, direction=direction_word,
          active_seat=active)

    def note_fault(seat: int, message: str) -> None:
        faults[seat] += 1
        if errors[seat] is None:
            errors[seat] = message

    def observation(seat: int, turn: dict) -> dict:
        players = [
            {"seat": i, "name": names_list[i], "count": len(hands[i]),
             "uno": i in declared and len(hands[i]) == 1}
            for i in range(n)
        ]
        return {
            "protocol": PROTOCOL, "game": GAME_ID, "rules_version": RULES_VERSION,
            "seat": seat, "players": players, "hand": hands[seat].to_list(),
            "discard_top": discard[-1], "active_color": color_state,
            "direction": "cw" if direction == 1 else "ccw", "active_seat": active,
            "pending_draw": pending, "turn": turn,
            "decision_number": decision_number + 1, "decision_cap": decision_cap,
        }

    def decide(seat: int, turn: dict, fallback: dict) -> tuple[dict, bool]:
        """Collect one decision; faults fall back deterministically (D4)."""
        nonlocal decision_number
        decision_number += 1
        if reset_failed[seat]:
            return dict(fallback), True
        try:
            raw = bots[seat].act(observation(seat, turn))
        except SandboxDown:
            raise
        except Exception as exc:  # noqa: BLE001 - timeout, crash, or invalid transport reply
            note_fault(seat, str(exc)[:200])
            return dict(fallback), True
        if type(raw) is dict:
            return raw, False
        note_fault(seat, "invalid action: not an object")
        return dict(fallback), True

    def serve_draw(seat: int, want: int, reason: str, faulted: bool = False) -> list[str]:
        """Draw up to `want` cards, reshuffling once when short (D11/D12)."""
        nonlocal discard
        if deck.remaining < want and len(discard) > 1:
            returned = discard[:-1]
            discard = discard[-1:]
            deck.discard(returned)
            deck.shuffle()
            log.append({"type": "reshuffle", "seat": seat, "reason": reason,
                        "returned": len(returned)})
            frame("reshuffle", count=len(returned))
        drawn = deck.draw(min(want, deck.remaining))
        for drawn_card_id in drawn:
            hands[seat].add(drawn_card_id)
        log.append({"type": "draw", "seat": seat, "reason": reason, "fault": faulted,
                    "cards": list(drawn), "count": len(drawn)})
        return drawn

    def end_turn() -> None:
        nonlocal active, stage
        active = (active + direction) % n
        stage = "play"

    def validate_play(action: dict, seat: int) -> tuple[str, str | None] | None:
        card = action.get("card")
        if type(card) is not str or card not in hands[seat]:
            return None
        if not matches(card, discard[-1], color_state):
            return None
        if is_wild(card):
            color = action.get("color")
            if type(color) is not str or len(color) != 1 or color not in COLORS:
                return None
            return card, color
        return card, None

    def open_challenge() -> None:
        nonlocal active, pending, stage
        active = (wdf_player + direction) % n
        pending = 4
        stage = "challenge"

    def run_effects(seat: int, face: str) -> None:
        """Apply a played card's effect on the seat that finished their turn."""
        nonlocal active, direction, pending, stage
        if face == "skip":
            frame("skip", seat=(active + direction) % n)
            active = (active + 2 * direction) % n
            stage = "play"
        elif face == "reverse":
            if n == 2:
                frame("skip", seat=(active + direction) % n)
                stage = "play"  # two-player reverse acts as a skip
            else:
                direction = -direction
                frame("reverse", seat=seat, direction="cw" if direction == 1 else "ccw")
                active = (active + direction) % n
                stage = "play"
        elif face == "draw2":
            pending = 2
            active = (active + direction) % n
            stage = "penalty"
        else:
            active = (active + direction) % n
            stage = "play"

    def apply_play(seat: int, card_id: str, color: str | None, faulted: bool) -> None:
        nonlocal stage, color_state, terminal, winner_seats, final_action
        nonlocal wdf_player, wdf_card, wdf_color, wdf_legal, wdf_last, cont
        hands[seat].remove(card_id)
        discard.append(card_id)
        prev_color = color_state
        color_state = color if is_wild(card_id) else card_color(card_id)
        face = card_face(card_id)
        log.append({"type": "play", "seat": seat, "card": card_id, "color": color_state,
                    "fault": faulted, "hand_after": hands[seat].to_list()})
        wild = is_wild(card_id)
        frame("play", seat=seat, card=card_id, **({"color": color_state} if wild else {}))
        final_action = {"type": "play", "seat": seat, "card": card_id,
                        **({"color": color_state} if wild else {})}
        remaining = len(hands[seat])
        wild4 = face == "wild4"
        wdf_last = False
        if wild4:
            wdf_player, wdf_card, wdf_color = seat, card_id, color_state
            wdf_legal = not any(card_color(owned) == prev_color for owned in hands[seat])
            wdf_last = remaining == 0
        if remaining == 0 and not wild4:
            winner_seats = [seat]
            terminal = "win"
            return
        if remaining == 1:
            cont = ("challenge",) if wild4 else ("effects", face)
            stage = "uno"
            return
        if wild4:
            cont = ("effects", face)
            open_challenge()
            return
        run_effects(seat, face)

    def do_draw(seat: int, faulted: bool) -> None:
        """Voluntary draw-one; a playable drawn card opens the post-draw window."""
        nonlocal stage, drawn_card, final_action
        drawn = serve_draw(seat, 1, "turn", faulted)
        frame("draw", seat=seat, count=len(drawn))
        final_action = {"type": "draw", "seat": seat, "count": len(drawn)}
        if drawn and matches(drawn[0], discard[-1], color_state):
            drawn_card = drawn[0]
            stage = "post_draw"
        else:
            end_turn()

    while terminal is None:
        if stage == "play" and decision_number >= decision_cap:
            terminal = "cap"
            break
        if stage == "play":
            seat = active
            action, faulted = decide(seat, {"type": "play"}, {"type": "draw"})
            kind = action.get("type")
            if kind == "play":
                played = validate_play(action, seat)
                if played is None:
                    if not faulted:
                        note_fault(seat, "invalid play action")
                    do_draw(seat, True)
                else:
                    apply_play(seat, played[0], played[1], faulted)
            elif kind == "draw":
                do_draw(seat, faulted)
            else:
                if not faulted:
                    note_fault(seat, "invalid play action")
                do_draw(seat, True)
        elif stage == "post_draw":
            seat = active
            action, faulted = decide(
                seat, {"type": "post_draw", "card": drawn_card}, {"type": "pass"})
            kind = action.get("type")
            played = None
            if kind == "play":
                candidate = validate_play(action, seat)
                if candidate is None or candidate[0] != drawn_card:
                    if not faulted:
                        note_fault(seat, "invalid post-draw action")
                else:
                    played = candidate
            elif kind != "pass" and not faulted:
                note_fault(seat, "invalid post-draw action")
            if played is not None:
                apply_play(seat, played[0], played[1], faulted)
            else:
                log.append({"type": "pass", "seat": seat, "fault": faulted,
                            "stage": "post_draw"})
                frame("pass", seat=seat)
                final_action = {"type": "pass", "seat": seat}
                end_turn()
        elif stage == "penalty":
            seat = active
            action, faulted = decide(
                seat, {"type": "penalty", "draw": pending}, {"type": "draw"})
            if action.get("type") != "draw" and not faulted:
                note_fault(seat, "penalty turn requires a draw")
            served = serve_draw(seat, pending, "penalty", faulted)
            frame("penalty", seat=seat, count=len(served))
            final_action = {"type": "draw", "seat": seat, "count": len(served)}
            pending = 0
            end_turn()
        elif stage == "uno":
            seat = active
            action, faulted = decide(seat, {"type": "uno"}, {"type": "uno"})
            kind = action.get("type")
            if kind == "pass" and not faulted:
                served = serve_draw(seat, 2, "uno_catch")
                log.append({"type": "uno_penalty", "seat": seat, "count": len(served)})
                frame("uno_penalty", seat=seat, count=len(served))
                final_action = {"type": "draw", "seat": seat, "count": len(served)}
            else:
                if kind != "uno" and not faulted:
                    note_fault(seat, "invalid uno decision")
                declared.add(seat)
                log.append({"type": "uno", "seat": seat})
                frame("uno", seat=seat)
                final_action = {"type": "uno", "seat": seat}
            if cont[0] == "challenge":
                open_challenge()
            else:
                run_effects(seat, cont[1])
        elif stage == "challenge":
            challenger = active
            action, faulted = decide(
                challenger,
                {"type": "challenge", "player": wdf_player, "card": wdf_card,
                 "color": wdf_color, "draw": pending},
                {"type": "pass"},
            )
            kind = action.get("type")
            if kind == "challenge":
                guilty = not wdf_legal
                log.append({"type": "challenge", "seat": challenger, "fault": faulted})
                log.append({"type": "challenge_result", "seat": challenger,
                            "player": wdf_player, "guilty": guilty,
                            "legal": wdf_legal})
                frame("challenge", seat=challenger)
                frame("challenge_result", seat=challenger, player=wdf_player,
                      guilty=guilty)
                final_action = {"type": "challenge", "seat": challenger}
                if wdf_last:
                    if guilty:
                        # The caught last-card wild four refills its player; the
                        # match continues with the challenger's normal turn.
                        served = serve_draw(wdf_player, 4, "challenge")
                        frame("penalty", seat=wdf_player, count=len(served))
                        pending = 0
                        stage = "play"
                    else:
                        winner_seats = [wdf_player]
                        terminal = "win"
                elif guilty:
                    served = serve_draw(wdf_player, 4, "challenge")
                    frame("penalty", seat=wdf_player, count=len(served))
                    pending = 0
                    stage = "play"
                else:
                    pending = 6
                    stage = "penalty"
            else:
                if kind != "pass" and not faulted:
                    note_fault(challenger, "invalid challenge decision")
                log.append({"type": "pass", "seat": challenger, "fault": faulted,
                            "stage": "challenge"})
                frame("pass", seat=challenger)
                final_action = {"type": "pass", "seat": challenger}
                if wdf_last:
                    winner_seats = [wdf_player]
                    terminal = "win"
                else:
                    stage = "penalty"  # pending stays at 4 on the challenger

    if terminal == "cap":
        fewest = min(counts())
        winner_seats = [i for i in range(n) if counts()[i] == fewest]
    frame("end", reason=terminal, winner_seats=winner_seats)
    log.append({"type": "end", "reason": terminal, "winner_seats": winner_seats,
                "hands": [hand.to_list() for hand in hands], "discard": list(discard),
                "draw_remaining": deck.remaining,
                "direction": "cw" if direction == 1 else "ccw"})
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
        "final_action": final_action,
        "names": names_list,
        "log": log,
        "frames": {"game": GAME_ID, "protocol": PROTOCOL, "names": names_list,
                   "frames": frames},
    }
