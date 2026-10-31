"""Independent Chip Model calculator, matching how the platform settles tables
that reach the hand cap. Your remaining chips become expected points, so chip
preservation matters even when you cannot win the hand outright.

Standalone and dependency-free. Use it from the simulator or directly:

    python icm.py 6000 3000 1500 1000
    python icm.py 6000 3000 1500 1000 --payouts 8,5,3,2,1,0,0,0
"""

from __future__ import annotations

PLATFORM_PAYOUTS = [8, 5, 3, 2, 1, 0, 0, 0]


def icm(stacks, payouts=None):
    """Expected payout for each stack under the given payout schedule.

    ``stacks`` are the surviving chip counts and ``payouts`` the points (or
    prizes) awarded top-down. The returned values sum to sum(payouts) and give
    each stack its equity-weighted share. Extra stacks beyond the payout list
    receive 0. Zero-chip stacks receive 0.
    """
    if payouts is None:
        payouts = PLATFORM_PAYOUTS
    n = len(stacks)
    memo = {}

    def walk(mask, place):
        key = (mask, place)
        cached = memo.get(key)
        if cached is not None:
            return cached
        result = [0.0] * n
        total = sum(stacks[i] for i in range(n) if mask & (1 << i))
        if total and place < len(payouts):
            for i in range(n):
                if not mask & (1 << i):
                    continue
                probability = stacks[i] / total
                result[i] += probability * payouts[place]
                sub = walk(mask ^ (1 << i), place + 1)
                for j in range(n):
                    result[j] += probability * sub[j]
        memo[key] = tuple(result)
        return memo[key]

    return list(walk((1 << n) - 1, 0))


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Independent Chip Model calculator")
    parser.add_argument("stacks", nargs="+", type=int, help="surviving chip counts")
    parser.add_argument("--payouts", default=",".join(map(str, PLATFORM_PAYOUTS)),
                        help="comma-separated points/prizes awarded top-down")
    args = parser.parse_args()
    payouts = [int(part) for part in args.payouts.split(",") if part.strip()]
    shares = icm(args.stacks, payouts)
    width = max(len(str(stack)) for stack in args.stacks)
    for index, (stack, share) in enumerate(zip(args.stacks, shares)):
        print(f"stack {index}: {stack:>{width}} chips -> {share:.4f} expected points")


if __name__ == "__main__":
    main()
