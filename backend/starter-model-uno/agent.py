"""Example CPU model agent for Stack Theory UNO v1.

A tiny linear scorer over hand-crafted per-card features, driven by
weights.json so you can replace the numbers without touching code. Uses only
NumPy and the observation it receives — never hidden state.
"""
import json
from pathlib import Path

import numpy as np

COLORS = "rygb"
WILD = "w"


class Agent:
    def __init__(self):
        self.weights = json.loads(Path(__file__).with_name("weights.json").read_text())

    def reset(self):
        """Called by the engine before every match."""

    def act(self, observation):
        turn = observation["turn"]
        kind = turn["type"]
        if kind == "penalty":
            return {"type": "draw"}
        if kind == "uno":
            return {"type": "uno"}
        if kind == "challenge":
            own = observation["players"][observation["seat"]]["count"]
            score = float(
                self.weights["challenge_bias"]
                + self.weights["own_count"] * own
                + self.weights["pending_draw"] * observation["pending_draw"]
            )
            if score >= self.weights["challenge_threshold"]:
                return {"type": "challenge"}
            return {"type": "pass"}
        if kind == "post_draw":
            card = turn["card"]
            if card[0] != WILD or self._out_of_hoard(observation):
                action = {"type": "play", "card": card}
                if card[0] == WILD:
                    action["color"] = self._best_color(observation["hand"])
                return action
            return {"type": "pass"}  # keep the drawn wild for later
        # Normal turn: score every legal card, play the best above threshold.
        legal = [card for card in observation["hand"] if self._playable(card, observation)]
        if not legal:
            return {"type": "draw"}
        best, best_score = None, None
        for card in sorted(legal):
            score = float(np.dot(self._features(card, observation),
                                 self.weights["card_weights"]))
            if best_score is None or score > best_score:
                best, best_score = card, score
        only_wilds = all(card[0] == WILD for card in legal)
        if best_score < self.weights["play_threshold"] and not only_wilds:
            return {"type": "draw"}
        action = {"type": "play", "card": best}
        if best[0] == WILD:
            action["color"] = self._best_color(observation["hand"])
        return action

    @staticmethod
    def _features(card, observation):
        hand = observation["hand"]
        return np.array([
            1.0,
            1.0 if card[0] == observation["active_color"] else 0.0,
            1.0 if card[1:-1] == observation["discard_top"][1:-1] else 0.0,
            1.0 if card[1:-1] in ("skip", "reverse", "draw2") else 0.0,
            1.0 if card[0] == WILD else 0.0,
            sum(1 for other in hand if other[0] == card[0]) / 10.0,
        ], dtype=float)

    @staticmethod
    def _playable(card, observation):
        if card[0] == WILD:
            return True
        return (card[0] == observation["active_color"]
                or card[1:-1] == observation["discard_top"][1:-1])

    def _out_of_hoard(self, observation):
        return (observation["players"][observation["seat"]]["count"]
                <= self.weights["keep_wild_hand_max"])

    @staticmethod
    def _best_color(hand):
        return max(COLORS, key=lambda color: sum(1 for card in hand if card[0] == color))
