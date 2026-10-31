"""Local table simulator for your Agent. A practice approximation of the platform.

Runs the same contract as the server: eight-bot sit-and-go, 2,000 chips,
blinds 10/20 doubling every 25 hands, points 8/5/3/2/1/0/0/0 by finishing
position, and ICM settlement (see icm.py) at the hand cap. Observations carry
exactly the fields the platform sends, and a raise amount is your TOTAL
contribution on the current street, not the increment.

This is NOT the platform engine. The server deals from a seeded deck through
PokerKit and runs your Agent inside an isolated Docker supervisor with a
per-decision deadline; a timed-out or crashing worker folds for the rest of
the table. This simulator is pure standard library and deterministic by seed,
built for fast iteration between practice runs.

Usage:
    python simulate.py [--hands 30] [--seed 42] [--stack 2000] [-v]
"""
from __future__ import annotations

import argparse
import random
from itertools import combinations

from agent import Agent
from icm import icm

RANKS = "23456789TJQKA"
PAYOUTS = [8, 5, 3, 2, 1, 0, 0, 0]
STARTING_STACK = 2000
MAX_DECISIONS_PER_STREET = 8192


def rank5(cards):
    """Comparable strength tuple of exactly five (rank_index, suit) cards."""
    rs = sorted((r for r, _ in cards), reverse=True)
    groups = {}
    for r in rs:
        groups[r] = groups.get(r, 0) + 1
    levels = sorted(groups.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    flush = len({s for _, s in cards}) == 1
    straight = None
    if len(groups) == 5:
        if rs[0] - rs[4] == 4:
            straight = rs[0]
        elif rs == [14, 5, 4, 3, 2]:
            straight = 5
    if flush and straight:
        return (8, straight)
    if levels[0][1] == 4:
        return (7, levels[0][0], levels[1][0])
    if levels[0][1] == 3 and levels[1][1] == 2:
        return (6, levels[0][0], levels[1][0])
    if flush:
        return (5, *rs)
    if straight:
        return (4, straight)
    if levels[0][1] == 3:
        return (3, levels[0][0], levels[1][0], levels[2][0])
    if levels[0][1] == 2 and levels[1][1] == 2:
        return (2, levels[0][0], levels[1][0], levels[2][0])
    if levels[0][1] == 2:
        return (1, levels[0][0], levels[1][0], levels[2][0], levels[3][0])
    return (0, *rs)


def best_hand(cards):
    """Strength of the best five-card hand out of five to seven cards."""
    parsed = [(RANKS.index(card[0]) + 2, card[1]) for card in cards]
    return max(rank5(list(pick)) for pick in combinations(parsed, 5))


class Baseline:
    """Local copies of the platform's transparent sparring bots."""

    def __init__(self, name, style):
        self.name, self.style = name, style

    def act(self, observation):
        legal = observation["legal_actions"]
        ranks = RANKS
        cards = observation["hole_cards"]
        high = max(ranks.index(c[0]) + 2 for c in cards)
        pair = cards[0][0] == cards[1][0]
        suited = cards[0][1] == cards[1][1]
        strong = pair or high >= (12 if self.style % 2 else 13) or (suited and high >= 10)
        if "raise" in legal and strong and self.style in (1, 3, 5, 7):
            return {"action": "raise", "amount": observation["min_raise"]}
        if "check" in legal:
            return {"action": "check"}
        if ("call" in legal and (strong or self.style in (0, 2, 6))
                and observation["to_call"] <= observation["stack"] // (3 if self.style != 6 else 1)):
            return {"action": "call"}
        return {"action": "fold"}


def make_opponents(count=7):
    names = ("Caller", "Raiser", "Steady", "Pairs", "Tight", "Suited", "Defender", "Pressure")
    return [Baseline(names[i], i) for i in range(count)]


class LocalTable:
    def __init__(self, bots, seed, starting_stack=STARTING_STACK, log=None):
        if not 2 <= len(bots) <= 8:
            raise ValueError("Tables support 2 to 8 bots")
        self.rng = random.Random(seed)
        self.bots = bots
        self.n = len(bots)
        self.starting_stack = starting_stack
        self.log = log if log is not None else (lambda *_: None)
        self.stacks = [starting_stack] * self.n
        self.points = [0.0] * self.n
        self.faults = [0] * self.n
        self.errors = [None] * self.n
        self.button = self.n - 1
        self.failed_reset = [False] * self.n
        for i, bot in enumerate(self.bots):
            reset = getattr(bot, "reset", None)
            if reset is None:
                continue
            try:
                reset()
            except Exception as exc:
                self.failed_reset[i] = True
                self.faults[i] += 1
                self.errors[i] = str(exc)[:200]

    def _next_alive(self, seat, alive):
        return next((seat + k) % self.n for k in range(1, self.n + 1) if (seat + k) % self.n in alive)

    def play_hand(self, hand):
        alive = [i for i in range(self.n) if self.stacks[i] > 0]
        if len(alive) <= 1:
            return False
        self.button = self._next_alive(self.button, alive)
        players = alive
        small = 10 * 2 ** ((hand - 1) // 25)
        sb_seat = self.button if len(alive) == 2 else self._next_alive(self.button, alive)
        bb_seat = self._next_alive(sb_seat, alive)
        hole, deck_iter = self._deal(players)
        self.hand = hand
        contrib = {s: 0 for s in players}
        street_bet = {s: 0 for s in players}
        folded, allin, acted = set(), set(), set()
        pot, level = 0, 0
        raise_size = 2 * small
        board, history = [], []
        self.log(f"Hand {hand} · blinds {small}/{2 * small} · button seat {self.button}")
        for seat, amount in ((sb_seat, small), (bb_seat, 2 * small)):
            self._commit(seat, min(amount, self.stacks[seat]), street_bet, contrib, allin)
        level = max(street_bet.values())
        streets = ("preflop", "flop", "turn", "river")
        for street_index, street in enumerate(streets):
            if street_index:
                count = 3 if street_index == 1 else 1
                board.extend(next(deck_iter) for _ in range(count))
                self.log(f"  {street} {' '.join(board)}")
            if street_index == 0:
                first = self._next_alive(bb_seat, alive)
            else:
                first = self._next_alive(self.button, alive)
            if sum(s not in folded and s not in allin for s in players) > 1:
                self._betting_round(first, street, players, hole, board, pot, street_bet,
                                    contrib, folded, allin, acted, level, raise_size, history)
            pot += sum(street_bet.values())
            street_bet = {s: 0 for s in players}
            acted, level, raise_size = set(), 0, 2 * small
            if len([s for s in players if s not in folded]) <= 1:
                break
        self._settle(players, hole, board, pot, contrib, folded, street_bet)
        return True

    def _deal(self, players):
        deck = [r + s for r in RANKS for s in "cdhs"]
        self.rng.shuffle(deck)
        deck_iter = iter(deck)
        hole = {seat: [next(deck_iter), next(deck_iter)] for seat in players}
        return hole, deck_iter

    def _commit(self, seat, pay, street_bet, contrib, allin):
        pay = min(pay, self.stacks[seat])
        self.stacks[seat] -= pay
        street_bet[seat] += pay
        contrib[seat] += pay
        if self.stacks[seat] == 0:
            allin.add(seat)

    def _observation(self, seat, street, players, hole, board, pot, street_bet, folded,
                     level, raise_size, history, to_call, can_raise):
        min_to = level + raise_size if can_raise else None
        max_to = street_bet[seat] + self.stacks[seat] if can_raise else None
        return {
            "hand": self.hand, "street": street, "seat": seat, "button": self.button,
            "hole_cards": list(hole[seat]), "board": list(board),
            "pot": pot + sum(street_bet.values()), "stack": self.stacks[seat],
            "to_call": to_call,
            "min_raise": min_to, "max_raise": max_to,
            "legal_actions": (["fold", "check" if to_call == 0 else "call"]
                              + (["raise"] if can_raise else [])),
            "players": [{"seat": s, "stack": self.stacks[s], "bet": street_bet[s],
                         "folded": s in folded} for s in players],
            "history": [dict(item) for item in history],
        }

    def _betting_round(self, first, street, players, hole, board, pot, street_bet,
                       contrib, folded, allin, acted, level, raise_size, history):
        pointer = players.index(first)
        decisions = 0
        while True:
            pending = [s for s in players
                       if s not in folded and s not in allin
                       and (s not in acted or street_bet[s] < level)]
            if not pending or len([s for s in players if s not in folded]) <= 1:
                return
            decisions += 1
            if decisions > MAX_DECISIONS_PER_STREET:
                raise RuntimeError("Local betting round stalled; please report this seed")
            if players[pointer] not in pending:
                pointer = (pointer + 1) % len(players)
                continue
            seat = players[pointer]
            to_call = level - street_bet[seat]
            can_raise = self.stacks[seat] > to_call
            observation = self._observation(seat, street, players, hole, board, pot,
                                            street_bet, folded, level, raise_size,
                                            history, to_call, can_raise)
            try:
                if self.failed_reset[seat]:
                    raise ValueError("reset failed")
                decision = self.bots[seat].act(observation)
                if not isinstance(decision, dict) or decision.get("action") not in observation["legal_actions"]:
                    raise ValueError("illegal action")
                action, amount = decision["action"], decision.get("amount")
                if action == "raise":
                    min_to, max_to = observation["min_raise"], observation["max_raise"]
                    if type(amount) is not int or not (min_to <= amount <= max_to or amount == max_to):
                        raise ValueError("illegal raise")
            except Exception as exc:
                self.faults[seat] += 1
                if self.errors[seat] is None:
                    self.errors[seat] = str(exc)[:200]
                action = "check" if to_call == 0 else "fold"
                amount = None
            if action == "fold":
                folded.add(seat)
                acted.add(seat)
                self.log(f"  P{seat} folds")
            elif action in ("check", "call"):
                self._commit(seat, to_call, street_bet, contrib, allin)
                acted.add(seat)
                self.log(f"  P{seat} {'checks' if to_call == 0 else 'calls ' + str(to_call)}")
            else:
                previous_level = level
                self._commit(seat, amount - street_bet[seat], street_bet, contrib, allin)
                raise_size = max(raise_size, amount - previous_level)
                level = amount
                acted = {seat}
                self.log(f"  P{seat} raises to {amount}")
            history.append({"seat": seat, "action": action,
                            "amount": amount if action == "raise" else None, "street": street})
            pointer = (pointer + 1) % len(players)

    def _settle(self, players, hole, board, pot, contrib, folded, street_bet):
        pot += sum(street_bet.values())
        contenders = [s for s in players if s not in folded]
        if len(contenders) == 1:
            self._award([contenders[0]], pot, hole, board)
        else:
            levels = sorted({contrib[s] for s in players if contrib[s] > 0})
            previous, carry = 0, 0
            for top in levels:
                layer = sum(max(0, min(contrib[s], top) - previous) for s in players)
                previous = top
                eligible = [s for s in contenders if contrib[s] >= top]
                if not eligible:
                    carry += layer
                    continue
                layer += carry
                carry = 0
                strength = {s: best_hand(hole[s] + board) for s in eligible}
                winning = max(strength.values())
                winners = [s for s in eligible if strength[s] == winning]
                self._award(winners, layer, hole, board, split=True)
            if carry:
                self._award(contenders, carry, hole, board, split=True)
        busted = [s for s in players if self.stacks[s] == 0]
        if busted:
            prior_alive = len(players)
            values = [PAYOUTS[pos - 1] for pos in range(prior_alive - len(busted) + 1, prior_alive + 1)]
            for seat in busted:
                self.points[seat] = sum(values) / len(busted)

    def _award(self, winners, amount, hole, board, split=False):
        if split:
            share, remainder = divmod(amount, len(winners))
            for index, seat in enumerate(winners):
                self.stacks[seat] += share + (remainder if index == 0 else 0)
        else:
            self.stacks[winners[0]] += amount
        cards = " ".join(hole[winners[0]])
        self.log(f"  -> P{winners[0]} wins {amount}" + (f" ({cards})" if board else ""))

    def run(self, max_hands):
        hands = 0
        for hand in range(1, max_hands + 1):
            if not self.play_hand(hand):
                break
            hands = hand
        alive = [i for i in range(self.n) if self.stacks[i] > 0]
        for seat, value in zip(alive, icm([self.stacks[s] for s in alive], PAYOUTS[:len(alive)])):
            self.points[seat] += value
        return {"points": self.points, "chips": self.stacks, "faults": self.faults,
                "errors": self.errors, "hands": hands}


def run_table(agent_class, seed, max_hands=30, starting_stack=STARTING_STACK, verbose=False):
    """Run one full table: your Agent in seat 0 against the platform baselines."""
    def log(message):
        if verbose:
            print(message)

    bots = [agent_class(), *make_opponents(7)]
    table = LocalTable(bots, seed, starting_stack, log=log)
    result = table.run(max_hands)
    result["names"] = ["Your Agent"] + [
        getattr(bot, "name", f"Opponent {i}") for i, bot in enumerate(bots[1:], 1)
    ]
    return result


def main():
    parser = argparse.ArgumentParser(description="Practice your Agent against local baselines.")
    parser.add_argument("--hands", type=int, default=30, help="hand cap for the table (default 30)")
    parser.add_argument("--seed", type=int, default=None, help="deterministic deck seed")
    parser.add_argument("--stack", type=int, default=STARTING_STACK, help="starting chips (default 2000)")
    parser.add_argument("-v", "--verbose", action="store_true", help="print every decision")
    args = parser.parse_args()
    seed = args.seed if args.seed is not None else random.randrange(2 ** 31)
    print(f"Local table · seed {seed} · {args.hands}-hand cap · raise = total street contribution\n")
    result = run_table(Agent, seed, max_hands=args.hands, starting_stack=args.stack, verbose=args.verbose)
    print(f"{'bot':<12}{'points':>10}{'chips':>10}{'faults':>8}  first error")
    for i, name in enumerate(result["names"]):
        print(f"{name:<12}{result['points'][i]:>10.3f}{result['chips'][i]:>10}{result['faults'][i]:>8}  {result['errors'][i] or ''}")
    print(f"\nPoints conserve to {sum(result['points']):g} (the payout table); "
          f"chips conserve to {sum(result['chips'])}.")
    print("This is a local approximation — confirm on the platform with a practice run.")


if __name__ == "__main__":
    main()
