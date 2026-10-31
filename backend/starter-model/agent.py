"""Example CPU model agent. Replace the weights and decision rule with your own."""
import json
from pathlib import Path


class Agent:
    def __init__(self):
        self.weights = json.loads(Path(__file__).with_name('weights.json').read_text())

    def act(self, observation):
        ranks = '23456789TJQKA'
        cards = observation['hole_cards']
        high = max(ranks.index(card[0]) + 2 for card in cards) / 14
        pair = float(cards[0][0] == cards[1][0])
        score = self.weights['bias'] + self.weights['high'] * high + self.weights['pair'] * pair
        legal = observation['legal_actions']
        if score >= self.weights['raise_threshold'] and 'raise' in legal:
            return {'action': 'raise', 'amount': observation['min_raise']}
        if 'check' in legal:
            return {'action': 'check'}
        if score >= self.weights['call_threshold'] and 'call' in legal:
            return {'action': 'call'}
        return {'action': 'fold'}
