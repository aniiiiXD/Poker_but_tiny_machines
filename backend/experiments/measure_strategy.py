"""Measure successful decision latency inside the real Docker supervisor.

This is not Sequoia's environment. Measured wall time includes worker scheduling,
JSON parsing and reply serialization inside the sandbox; it excludes host/Docker
transport and table simulation. Timeouts and errors are listed separately.
"""
import argparse
import math
import random
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from arena.baselines import make_baselines
from arena.engine import play_table
from arena.sandbox import ContainerBot


class MeasuredBot(ContainerBot):
    def __init__(self, path):
        super().__init__(path, 'Your strategy', decision_ms=1.0)
        self.times = []
        self.actions = Counter()
        self.errors = []
        self.streets = Counter()

    def act(self, obs):
        try:
            result = super().act(obs)
        except Exception as exc:
            self.errors.append(str(exc))
            raise
        if self.last_elapsed_ms is not None:
            self.times.append(self.last_elapsed_ms)
        self.actions[result['action']] += 1
        self.streets[obs['street']] += 1
        return result


def percentile(values, pct):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * pct) - 1)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tables', type=int, default=16)
    parser.add_argument('--hands', type=int, default=50)
    parser.add_argument('--seed', type=int, default=20261101)
    args = parser.parse_args()
    if not 1 <= args.tables <= 128 or not 1 <= args.hands <= 200:
        parser.error('Use 1–128 tables and 1–200 hands.')
    times, actions, streets, errors = [], Counter(), Counter(), Counter()
    points, chips, actual_hands, table_faults = [], [], 0, 0
    for i in range(args.tables):
        bot = MeasuredBot(ROOT / 'experiments/aggression_bluff_bot.py')
        opponents = make_baselines(8)
        opponents.pop(i % 8)
        random.Random(args.seed + i * 997).shuffle(opponents)
        seat = (i // 2) % 8
        bots = opponents[:]
        bots.insert(seat, bot)
        try:
            result = play_table(bots, seed=args.seed + i, max_hands=args.hands, capture=False)
            times.extend(bot.times)
            actions.update(bot.actions)
            streets.update(bot.streets)
            errors.update(bot.errors)
            points.append(result['points'][seat])
            chips.append(result['chips'][seat])
            actual_hands += result['hands']
            table_faults += result['faults'][seat]
        finally:
            bot.close()
    print(f'Tables: {args.tables}; max hands: {args.hands}; actual hands: {actual_hands}; seed: {args.seed}')
    print(f'Successful timed decisions: {len(times)}; recorded faults: {table_faults}; mean points: {statistics.mean(points):.3f}; mean chips: {statistics.mean(chips):.0f}')
    if times:
        print(f'Time in milliseconds: mean={statistics.mean(times):.4f}, median={statistics.median(times):.4f}, p95={percentile(times, 0.95):.4f}, p99={percentile(times, 0.99):.4f}, max={max(times):.4f}')
        bins = ((0, 0.025), (0.025, 0.05), (0.05, 0.1), (0.1, 0.25), (0.25, 0.5), (0.5, 1.0))
        print('Decision time histogram (ms):')
        for low, high in bins:
            count = sum(low <= value < high for value in times)
            print(f'  {low:>5.3f}–{high:<5.3f}: {count:>5}  {count / len(times) * 100:>5.1f}%')
    print('Actions:', ', '.join(f'{key}={actions[key]}' for key in ('fold', 'check', 'call', 'raise')))
    print('Streets:', ', '.join(f'{key}={streets[key]}' for key in ('preflop', 'flop', 'turn', 'river')))
    print('Errors:', dict(errors))


if __name__ == '__main__':
    main()
