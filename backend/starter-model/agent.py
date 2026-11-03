"""Example CPU model agent. Replace the weights and decision rule with your own."""
import json
from pathlib import Path

import numpy as np


class Agent:
    def __init__(self):
        self.weights = json.loads(Path(__file__).with_name('weights.json').read_text())
        self.coefficients = np.array([self.weights['high'], self.weights['pair']], dtype=np.float32)

    def act(self, observation):
        ranks = '23456789TJQKA'
        cards = observation['hole_cards']
        high = max(ranks.index(card[0]) + 2 for card in cards) / 14
        pair = float(cards[0][0] == cards[1][0])
        features = np.array([high, pair], dtype=np.float32)
        score = float(self.weights['bias'] + np.dot(self.coefficients, features))
        legal = observation['legal_actions']
        if score >= self.weights['raise_threshold'] and 'raise' in legal:
            return {'action': 'raise', 'amount': observation['min_raise']}
        if 'check' in legal:
            return {'action': 'check'}
        if score >= self.weights['call_threshold'] and 'call' in legal:
            return {'action': 'call'}
        return {'action': 'fold'}
