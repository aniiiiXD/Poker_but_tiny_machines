"""Example CPU model agent for Stack Theory Bluff v1.

A tiny logistic scorer over a hand-crafted feature, driven by weights.json so
you can replace the numbers without touching code. Uses only NumPy and the
observation it receives — never hidden state.
"""
import json
from pathlib import Path

import numpy as np

RANKS = "A23456789TJQK"


class Agent:
    def __init__(self):
        self.weights = json.loads(Path(__file__).with_name("weights.json").read_text())

    def act(self, observation):
        turn = observation["turn"]
        hand = observation["hand"]
        if turn["type"] == "play":
            rank = observation["required_rank"]
            truthful = [card for card in hand if card[0] == rank]
            if truthful:
                take = min(len(truthful), self.weights["max_truthful"])
                return {"type": "play", "cards": truthful[:take]}
            # Bluff with the lowest card; smaller bluffs are cheaper.
            return {"type": "play", "cards": [min(hand, key=lambda card: RANKS.index(card[0]))]}
        # Challenge score: how impossible is the claim?
        rank = turn["rank"]
        own = sum(1 for card in hand if card[0] == rank)
        revealed = sum(
            1
            for event in observation["history"]
            if event.get("type") == "resolution" and event.get("revealed")
            for card in event["revealed"]
            if card[0] == rank
        )
        score = float(
            self.weights["bias"]
            + self.weights["claim_weight"] * turn["count"]
            + self.weights["own_weight"] * own
            + self.weights["revealed_weight"] * revealed
        )
        if score >= self.weights["challenge_threshold"]:
            return {"type": "challenge"}
        return {"type": "pass"}
