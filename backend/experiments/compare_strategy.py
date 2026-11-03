"""Compare the proposed bot against local baselines using the real engine.

Run from backend/: uv run python experiments/compare_strategy.py --tables 32 --hands 40
This is a small exploratory benchmark, not an evaluation against Sequoia bots.
"""
import argparse
import importlib.util
import math
import random
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from arena.baselines import make_baselines
from arena.engine import play_table
from experiments.aggression_bluff_bot import Agent

spec = importlib.util.spec_from_file_location('arena_starter', ROOT / 'starter-kit' / 'agent.py')
starter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(starter)


class ConstantRandom:
    def random(self):
        return 1.0


class NoRandomAgent(Agent):
    def reset(self):
        self.rng = ConstantRandom()


class StarterAdapter:
    def reset(self):
        self.bot = starter.Agent()

    def act(self, observation):
        return self.bot.act(observation)


def standard_error(values):
    return statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else 0.0


def benchmark(tables, hands, seed):
    classes = [('Your strategy', Agent), ('Same rules, no random bluff/guess', NoRandomAgent),
               ('Existing starter bot', StarterAdapter)]
    data = {}
    for label, bot_class in classes:
        points, chips, faults, leaders, actual_hands = [], [], 0, 0, []
        opponent_points = []
        for iteration in range(tables):
            baselines = make_baselines(8)
            baselines.pop(iteration % 8)
            candidate = bot_class()
            candidate.name = label
            random.Random(seed + iteration * 997).shuffle(baselines)
            seat = (iteration // 8) % 8
            bots = baselines[:]
            bots.insert(seat, candidate)
            result = play_table(bots, seed + iteration, max_hands=hands, capture=False)
            points.append(result['points'][seat])
            chips.append(result['chips'][seat])
            opponent_points.extend(p for i, p in enumerate(result['points']) if i != seat)
            faults += sum(result['faults'])
            leaders += int(result['chips'][seat] == max(result['chips']))
            actual_hands.append(result['hands'])
        data[label] = {'points': points, 'chips': chips, 'faults': faults,
                       'leaders': leaders, 'hands': actual_hands, 'opponent_points': opponent_points}
    print(f'Tables per strategy: {tables}; hand cap: {hands}; starting chips per bot: 2000; seed: {seed}')
    print('Opponent pool: seven of the eight built-in baselines; omitted bot and seats rotate.')
    for label, row in data.items():
        print(f"{label}: mean points {statistics.mean(row['points']):.3f} "
              f"(SE {standard_error(row['points']):.3f}); mean ending chips {statistics.mean(row['chips']):.0f}; "
              f"chip leader {row['leaders']}/{tables}; faults across table {row['faults']}; "
              f"mean hands {statistics.mean(row['hands']):.1f}; "
              f"opponent mean points {statistics.mean(row['opponent_points']):.3f}")
    proposal = data['Your strategy']['points']
    for label in ('Same rules, no random bluff/guess', 'Existing starter bot'):
        diffs = [a - b for a, b in zip(proposal, data[label]['points'])]
        print(f"Paired point difference vs {label}: {statistics.mean(diffs):+.3f} "
              f"(paired SE {standard_error(diffs):.3f})")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--tables', type=int, default=32)
    parser.add_argument('--hands', type=int, default=40)
    parser.add_argument('--seed', type=int, default=5202601)
    args = parser.parse_args()
    if not 1 <= args.tables <= 1000 or not 1 <= args.hands <= 200:
        parser.error('Use 1–1000 tables and 1–200 hands.')
    benchmark(args.tables, args.hands, args.seed)
