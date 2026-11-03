"""Shared, game-agnostic machinery for Stack Theory games.

Currently the card/token engine in ``arena.games.common.deck`` (TICKET-001):
contract card identity, seeded shuffling, drawing, dealing, sorted hands and
face-down piles. Game engines import from the submodules directly.
"""
