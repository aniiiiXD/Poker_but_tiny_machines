"""Deterministic, transparent exhibition strategies."""

class Baseline:
    def __init__(self, name: str, style: int):
        self.name, self.style = name, style

    def reset(self):
        pass

    def act(self, observation: dict) -> dict:
        legal = observation['legal_actions']
        ranks = '23456789TJQKA'
        cards = observation['hole_cards']
        high = max(ranks.index(c[0]) + 2 for c in cards)
        pair = cards[0][0] == cards[1][0]
        suited = cards[0][1] == cards[1][1]
        strong = pair or high >= (12 if self.style % 2 else 13) or (suited and high >= 10)
        if 'raise' in legal and strong and self.style in (1, 3, 5, 7):
            return {'action': 'raise', 'amount': observation['min_raise']}
        if 'check' in legal:
            return {'action': 'check'}
        if 'call' in legal and (strong or self.style in (0, 2, 6)) and observation['to_call'] <= observation['stack'] // (3 if self.style != 6 else 1):
            return {'action': 'call'}
        return {'action': 'fold'}


def make_baselines(count: int = 8) -> list[Baseline]:
    if not 1 <= count <= 8:
        raise ValueError('count must be between 1 and 8')
    names = ('Caller', 'Raiser', 'Steady', 'Pairs', 'Tight', 'Suited', 'Defender', 'Pressure')
    return [Baseline(names[i], i) for i in range(count)]
