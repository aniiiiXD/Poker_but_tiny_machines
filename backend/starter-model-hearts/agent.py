"""Example CPU model agent for Stack Theory Hearts v1.

A tiny linear scorer over hand-crafted per-card features, driven by
weights.json so you can replace the numbers without touching code. Uses only
NumPy and the observation it receives — never hidden state.
"""
import json
from pathlib import Path

import numpy as np

STRENGTH = {rank: index for index, rank in enumerate("23456789TJQKA")}


class Agent:
    def __init__(self):
        self.weights = json.loads(Path(__file__).with_name("weights.json").read_text())

    def reset(self) -> None:
        """Called once per match by the arena; keep per-match state here."""

    def act(self, observation):
        hand = observation["hand"]
        if observation["turn"]["type"] == "pass":
            scores = np.array([self._pass_score(card) for card in hand])
            order = np.argsort(scores)[::-1]  # shed the highest-scoring dangers
            return {"type": "pass", "cards": [hand[i] for i in order[:3]]}
        legal = self._legal(observation)
        costs = np.array([self._play_cost(card, observation) for card in legal])
        return {"type": "play", "card": legal[int(np.argmin(costs))]}

    def _pass_score(self, card):
        rank, _ = STRENGTH[card[0]], card[1]
        w = self.weights
        return float(w["pass_bias"] + w["pass_rank_weight"] * rank
                     + w["pass_heart_weight"] * (card[1] == "h")
                     + w["pass_queen_weight"] * (card == "Qs"))

    def _play_cost(self, card, observation):
        trick = observation["trick"]
        w = self.weights
        would_win = 0
        trick_points = 0
        if trick:
            led = trick[0]["card"][1]
            best = max((play["card"] for play in trick if play["card"][1] == led),
                       key=lambda c: STRENGTH[c[0]])
            if card[1] == led and STRENGTH[card[0]] > STRENGTH[best[0]]:
                would_win = 1
            trick_points = sum(13 if play["card"] == "Qs" else play["card"][1] == "h"
                               for play in trick)
        else:
            would_win = 1  # a lead takes the trick for now
        features = np.array([
            1.0,
            STRENGTH[card[0]],
            float(card[1] == "h"),
            float(card == "Qs"),
            float(would_win),
            float(trick_points),
        ])
        theta = np.array([
            w["cost_bias"], w["cost_rank_weight"], w["cost_heart_weight"],
            w["cost_queen_weight"], w["cost_win_weight"], w["cost_trick_points_weight"],
        ])
        return float(theta @ features)

    @staticmethod
    def _legal(observation):
        hand = observation["hand"]
        trick = [play["card"] for play in observation["trick"]]
        if not trick:
            if observation["trick_number"] == 0:
                return ["2c"] if "2c" in hand else []
            if observation["hearts_broken"]:
                return list(hand)
            return [card for card in hand if card[1] != "h"] or list(hand)
        follow = [card for card in hand if card[1] == trick[0][1]]
        return follow or list(hand)
