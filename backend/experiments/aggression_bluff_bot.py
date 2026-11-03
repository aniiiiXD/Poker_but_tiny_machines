"""A simple hand-strength bot with occasional random bluffs and bluff guesses.

The random guess is a 50/50 decision aid, not a way to see an opponent's cards.
Only the Python standard library is used, so this is an Arena-compatible agent.
"""
import random

RANKS = '23456789TJQKA'


def hand_category(cards):
    """Return 0..8: high card, pair, two pair, trips, straight, flush,
    full house, quads, straight flush. Uses available hole + community cards.
    """
    counts = [0] * 15
    suits = {'c': [], 'd': [], 'h': [], 's': []}
    for card in cards:
        rank = RANKS.index(card[0]) + 2
        counts[rank] += 1
        suits[card[1]].append(rank)

    def straight(ranks):
        present = set(ranks)
        if 14 in present:
            present.add(1)
        return any(all(rank in present for rank in range(high - 4, high + 1))
                   for high in range(5, 15))

    flush_ranks = next((ranks for ranks in suits.values() if len(ranks) >= 5), None)
    if flush_ranks and straight(flush_ranks):
        return 8
    if 4 in counts:
        return 7
    trips = sum(count >= 3 for count in counts)
    pairs = sum(count >= 2 for count in counts)
    if trips and pairs >= 2:
        return 6
    if flush_ranks:
        return 5
    if straight(rank for rank, count in enumerate(counts) if count):
        return 4
    if trips:
        return 3
    if pairs >= 2:
        return 2
    if pairs:
        return 1
    return 0


class Agent:
    def __init__(self):
        # Fixed seed makes experiments repeatable without seeing the deck seed.
        self.rng = random.Random(2026)

    def reset(self):
        self.rng = random.Random(2026)

    def act(self, observation):
        legal = observation['legal_actions']
        hole = observation['hole_cards']
        board = observation['board']
        to_call = observation['to_call']
        pot = observation['pot']
        stack = observation['stack']
        price = to_call / max(1, pot + to_call)
        street = observation['street']
        history = observation.get('history', [])
        opponent_raises = sum(1 for action in history
                              if action['seat'] != observation['seat']
                              and action['street'] == street and action['action'] == 'raise')
        raise_counts = {}
        for action in history:
            if (action['seat'] != observation['seat'] and action['street'] == street
                    and action['action'] == 'raise'):
                seat = action['seat']
                raise_counts[seat] = raise_counts.get(seat, 0) + 1
        # A large price or repeated raises indicate pressure, not certainty of strength.
        super_aggressive = to_call > 0 and (
            max(raise_counts.values(), default=0) >= 2
            or to_call >= max(1, pot) * 0.65 or to_call >= max(1, stack) * 0.4
        )

        def raise_min():
            return {'action': 'raise', 'amount': observation['min_raise']}

        def check_call():
            if 'check' in legal:
                return {'action': 'check'}
            if 'call' in legal:
                return {'action': 'call'}
            return {'action': 'fold'}

        # A random bit cannot detect bluffing. We occasionally *guess* and only
        # use that guess to make a modest call, never to expose hidden cards.
        bluff_guess = False
        if to_call > 0 and not super_aggressive and self.rng.random() < 0.20:
            bluff_guess = self.rng.random() > 0.5

        if not board:
            first, second = (RANKS.index(card[0]) + 2 for card in hole)
            high, low = max(first, second), min(first, second)
            pair = first == second
            suited = hole[0][1] == hole[1][1]
            premium = (pair and high >= 10) or (high == 14 and low >= 12)
            playable = pair or (high >= 12 and low >= 10) or (suited and high >= 11 and low >= 9)
            if premium and 'raise' in legal and opponent_raises < 2:
                return raise_min()
            if 'check' in legal:
                return check_call()
            if playable and not super_aggressive and price <= 0.22:
                return check_call()
            if bluff_guess and high >= 12 and price <= 0.08:
                return check_call()
            return {'action': 'fold'} if 'fold' in legal else check_call()

        category = hand_category(hole + board)
        # Three of a kind or better: build the pot when raising is legal.
        if category >= 3:
            if 'raise' in legal:
                return raise_min()
            return check_call()

        # Two pair: play, but fold to the user's 'super aggressive' pressure.
        if category == 2:
            if super_aggressive and 'fold' in legal:
                return {'action': 'fold'}
            if 'raise' in legal and to_call == 0:
                return raise_min()
            return check_call()

        if category == 1:
            if 'check' in legal:
                return check_call()
            if not super_aggressive and price <= (0.16 if bluff_guess else 0.12):
                return check_call()
            return {'action': 'fold'} if 'fold' in legal else check_call()

        # Weak hands occasionally make a small bluff when nobody has bet.
        if 'check' in legal:
            if 'raise' in legal and self.rng.random() < 0.20 and self.rng.random() > 0.5:
                return raise_min()
            return check_call()
        # A four-card flush draw can justify a small call; this is a simple rule,
        # not a Monte Carlo estimate of win probability.
        cards = hole + board
        flush_draw = len(board) < 5 and max(sum(card[1] == suit for card in cards) for suit in 'cdhs') >= 4
        if not super_aggressive and price <= (0.12 if flush_draw else 0.06 if bluff_guess else 0):
            return check_call()
        return {'action': 'fold'} if 'fold' in legal else check_call()
