"""Trusted game registry: code-defined games, never user-supplied engines.

Each `GameSpec` pairs a stable game ID and immutable rules version with a
narrow adapter interface (baselines, match runner, smoke tests, starter
files). Submitted code can only ever reach the adapter's runtime bots, never
choose or inject server-side modules.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .bluff import baselines as bluff_baselines
from .bluff.engine import PROTOCOL as BLUFF_PROTOCOL
from .bluff.engine import RULES_VERSION as BLUFF_RULES_VERSION
from .bluff.engine import SEATS as BLUFF_SEATS
from .bluff.engine import _validate_cards, play_bluff_match

ROOT = Path(__file__).resolve().parents[2]


class GameError(ValueError):
    """Unknown game ID, unsupported rules version, or incompatible request."""


@dataclass(frozen=True)
class GameSpec:
    game_id: str
    rules_version: int
    display_name: str
    variant_label: str
    seats: tuple[int, ...]
    tracks: tuple[str, ...]
    protocol: int = 1
    adapter: object = field(default=None)

    def public(self) -> dict:
        return {
            "id": self.game_id,
            "name": self.display_name,
            "variant": self.variant_label,
            "rules_version": self.rules_version,
            "tracks": list(self.tracks),
            "seats": list(self.seats),
        }


class _EngineAdapter:
    """Shared behavior for the post-poker engines: uniform engine signature,
    baseline factories, sandbox smoke via a real short match, and platform
    match-score normalization (engines may expose native points separately)."""

    game = ""                     # module name under arena.games
    play = None                   # engine.play_<game>_match
    baselines = None              # baselines.make_<game>_baselines
    starter_files = ("agent.py", "README.md")
    interface = "class Agent:\n    def act(self, observation: dict) -> dict: ..."
    decision_ms = {"classic": 1.0, "model": 50.0}
    practice_param = "matches"
    smoke_cap = 120               # short-match budget for smoke/validation
    validation_seats = 4          # seat count for the sandbox smoke match

    def make_baselines(self, count: int = 4, seed: int = 0) -> list:
        return self.baselines(count, seed=seed)

    def run_match(self, bots, seed, config, capture=False):
        cap = int(config.get("decision_cap") or 500)
        return self.play(bots, seed, decision_cap=cap, capture=capture)

    def match_scores(self, result) -> list:
        return result["points"]

    def validation_match(self, bot) -> None:
        """Run one real short match with the bot in seat 0; any fault fails."""
        bots = [bot] + self.make_baselines(self.validation_seats - 1, seed=1729)
        result = self.play(bots, seed=1729, decision_cap=self.smoke_cap, capture=False)
        if result["faults"][0]:
            raise ValueError("Sandbox smoke test failed: " + str(result["errors"][0] or "bot fault"))

    def smoke(self, bot) -> None:
        """Reset + one full short match in the sandbox (the bluff P1 lesson)."""
        bot.reset()
        self.validation_match(bot)

    def rules_block(self, event, track: str, cooldown: int) -> dict:
        spec = self.spec
        return {
            "language": "Python 3.12 / standard library",
            "source_limit_bytes": 102400,
            "project_limit_bytes": 16777216 if track == "model" else None,
            "track": track,
            "network_access": False,
            "decision_ms": event["decision_ms"],
            "submission_cooldown_seconds": cooldown,
            "seats": list(spec.seats),
            "decision_cap": 500,
            "scoring": self.scoring_text,
            "sandbox_digest": event["sandbox_digest"],
        }


class UnoAdapter(_EngineAdapter):
    game = "uno"
    protocol = "uno"
    starter_dir = "starter-uno"
    smoke_cap = 120
    validation_seats = 2
    scoring_text = "Win = 1, loss = 0; at the decision cap (500) fewest cards wins and ties share. Standing is the average match score."

    def __init__(self):
        from .uno import baselines as b
        from .uno import engine as e

        self.engine, self.baselines = e, b.make_uno_baselines
        self.play = e.play_uno_match


class HeartsAdapter(_EngineAdapter):
    game = "hearts"
    protocol = "hearts"
    starter_dir = "starter-hearts"
    smoke_cap = 500  # a full hand is structurally bounded
    validation_seats = 4
    scoring_text = "Fewest penalty points wins (Q♠ 13, hearts 1 each; moon = shooter 0, others +26). Win = 1, loss = 0, ties share; standing is the average match score."

    def __init__(self):
        from .hearts import baselines as b
        from .hearts import engine as e

        self.engine, self.baselines = e, b.make_hearts_baselines
        self.play = e.play_hearts_match

    def match_scores(self, result) -> list:
        return result["match_points"]


class RummyAdapter(_EngineAdapter):
    game = "rummy"
    protocol = "rummy"
    starter_dir = "starter-rummy"
    smoke_cap = 120
    validation_seats = 2
    scoring_text = "First valid declaration wins (≥2 sequences, ≥1 pure). Win = 1, loss = 0, ties share; at the cap the lowest deadwood wins. Standing is the average match score."

    def __init__(self):
        from .rummy import baselines as b
        from .rummy import engine as e

        self.engine, self.baselines = e, b.make_rummy_baselines
        self.play = e.play_rummy_match


class HexchangeAdapter(_EngineAdapter):
    game = "hexchange"
    protocol = "hexchange"
    starter_dir = "starter-hexchange"
    smoke_cap = 200
    validation_seats = 3
    scoring_text = "First to 10 VP wins (settlement 1, city 2, VP card 1). Win = 1, loss = 0, ties share; at the cap the most VP wins. Standing is the average match score."

    def __init__(self):
        from .hexchange import baselines as b
        from .hexchange import engine as e

        self.engine, self.baselines = e, b.make_hexchange_baselines
        self.play = e.play_hexchange_match

    def make_baselines(self, count: int = 4, seed: int = 0) -> list:
        if count == 4:  # a full table: unique names per seat via the table factory
            from .hexchange.baselines import make_hexchange_table

            return make_hexchange_table(4, seed=seed)
        return self.baselines(count, seed=seed)

    def match_scores(self, result) -> list:
        return result["match_points"]


class PokerAdapter:
    def match_scores(self, result) -> list:
        return result["points"]

    """Wraps the existing eight-seat engine without changing its contract."""

    starter_dir = "starter-kit"
    starter_files = ("agent.py", "simulate.py", "icm.py", "README.md")
    interface = "class Agent:\n    def act(self, observation: dict) -> dict: ..."
    decision_ms = {"classic": 1.0, "model": 50.0}
    practice_param = "hands"
    protocol = "poker"

    def make_baselines(self, count: int = 8, seed: int = 0) -> list:
        from ..baselines import make_baselines

        return make_baselines(count)

    def run_match(self, bots, seed, config, capture=False):
        from ..engine import play_table

        return play_table(bots, seed, max_hands=config["max_hands"], capture=capture)

    def smoke(self, bot) -> None:
        observation = {
            "hand": 1, "street": "preflop", "seat": 0, "button": 1,
            "hole_cards": ["As", "Kd"], "board": [], "pot": 30,
            "stack": 2000, "to_call": 20, "min_raise": 40, "max_raise": 2000,
            "legal_actions": ["fold", "call", "raise"],
            "players": [{"seat": 0, "stack": 2000, "bet": 0, "folded": False},
                        {"seat": 1, "stack": 1980, "bet": 20, "folded": False}],
            "history": [],
        }
        bot.reset()
        action = bot.act(observation)
        if action.get("action") not in observation["legal_actions"]:
            raise ValueError("Sandbox smoke test returned an illegal action.")
        if action["action"] == "raise" and (
            type(action.get("amount")) is not int or not 40 <= action["amount"] <= 2000
        ):
            raise ValueError("Sandbox smoke test returned an illegal raise.")

    def validation_match(self, bot) -> None:
        from ..baselines import make_baselines
        from ..engine import play_table

        bots = make_baselines(8)
        bots[0] = bot
        result = play_table(bots, seed=1729, max_hands=1, capture=False)
        if result["faults"][0]:
            raise ValueError("Sandbox smoke test failed: " + str(result["errors"][0] or "bot fault"))

    def rules_block(self, event, track: str, cooldown: int) -> dict:
        return {
            "language": "Python 3.12 / standard library",
            "source_limit_bytes": 102400,
            "project_limit_bytes": 16777216 if track == "model" else None,
            "track": track,
            "network_access": False,
            "decision_ms": event["decision_ms"],
            "submission_cooldown_seconds": cooldown,
            "initial_chips": 2000,
            "blinds": "10/20, doubling every 25 hands",
            "payouts": [8, 5, 3, 2, 1, 0, 0, 0],
            "scoring": "Mean points per table; round weights 1 through 6. ICM at hand cap. Non-scoring copies fill empty seats.",
            "tie_policy": "Equal scores share a rank. No cash prizes are configured for the local pilot.",
            "sandbox_digest": event["sandbox_digest"],
        }


class BluffAdapter:
    """Stack Theory Bluff v1: four seats, challenges, hidden piles."""

    starter_dir = "starter-bluff"
    starter_files = ("agent.py", "README.md")
    interface = "class Agent:\n    def act(self, observation: dict) -> dict: ...  # bluff protocol 1"
    decision_ms = {"classic": 1.0, "model": 50.0}
    practice_param = "matches"
    protocol = "bluff"

    def match_scores(self, result) -> list:
        return result["points"]


    def make_baselines(self, count: int = 4, seed: int = 0) -> list:
        return bluff_baselines.make_bluff_baselines(count, seed=seed)

    def run_match(self, bots, seed, config, capture=False):
        return play_bluff_match(
            bots, seed,
            decision_cap=int(config.get("decision_cap") or 500),
            capture=capture,
        )

    def smoke(self, bot) -> None:
        """Require one legal play decision and one legal challenge decision."""
        base = {
            "protocol": BLUFF_PROTOCOL, "game": "bluff", "rules_version": BLUFF_RULES_VERSION,
            "players": [
                {"seat": 0, "name": "Smoke", "count": 3, "out": False},
                {"seat": 1, "name": "Claimant", "count": 4, "out": False},
                {"seat": 2, "name": "B3", "count": 3, "out": False},
                {"seat": 3, "name": "B4", "count": 3, "out": False},
            ],
            "required_rank": "A", "decision_number": 1, "decision_cap": 500,
        }
        play_observation = {
            **base, "seat": 0, "hand": ["Ac", "2d", "7s"], "pile_size": 0,
            "turn": {"type": "play"}, "history": [],
        }
        bot.reset()
        action = bot.act(play_observation)
        if not _validate_cards((action or {}).get("cards"), ["Ac", "2d", "7s"]):
            raise ValueError("Bluff smoke test returned an illegal play.")
        challenge_observation = {
            **base, "seat": 2, "hand": ["3h", "Kc", "9d"], "pile_size": 3,
            "turn": {"type": "challenge", "claimant": 1, "rank": "A", "count": 3},
            "history": [{"type": "play", "seat": 1, "rank": "A", "count": 3, "pile_size": 3}],
        }
        decision = bot.act(challenge_observation)
        if (decision or {}).get("type") not in ("challenge", "pass"):
            raise ValueError("Bluff smoke test returned an illegal challenge decision.")

    def validation_match(self, bot) -> None:
        bots = self.make_baselines(3, seed=1729)
        bots.insert(0, bot)
        result = play_bluff_match(bots, seed=1729, capture=False)
        if result["faults"][0]:
            raise ValueError("Sandbox smoke test failed: " + str(result["errors"][0] or "bot fault"))

    def rules_block(self, event, track: str, cooldown: int) -> dict:
        return {
            "language": "Python 3.12 / standard library",
            "source_limit_bytes": 102400,
            "project_limit_bytes": 16777216 if track == "model" else None,
            "track": track,
            "network_access": False,
            "decision_ms": event["decision_ms"],
            "submission_cooldown_seconds": cooldown,
            "seats": [BLUFF_SEATS],
            "deck": "Standard 52 cards; each dealt 13 per seat",
            "rank_cycle": "A, 2, 3–10, J, Q, K, then A again",
            "claim": "1–4 face-down cards claimed as the required rank; lying allowed",
            "challenge": "Sequential clockwise decisions from the next seat; first challenge stops the sequence",
            "scoring": "Win = 1, loss = 0; after 500 decisions the current claim resolves, then fewest cards wins and ties share the point. Standing is the average match score.",
            "decision_cap": 500,
            "sandbox_digest": event["sandbox_digest"],
        }


POKER = GameSpec(
    game_id="poker", rules_version=1, display_name="No-limit Texas Hold'em",
    variant_label="No-limit Texas Hold'em", seats=(2, 3, 4, 5, 6, 7, 8),
    tracks=("classic", "model"), protocol=1, adapter=PokerAdapter(),
)
BLUFF = GameSpec(
    game_id="bluff", rules_version=1, display_name="Bluff",
    variant_label="Stack Theory Bluff v1", seats=(BLUFF_SEATS,),
    tracks=("classic", "model"), protocol=BLUFF_PROTOCOL, adapter=BluffAdapter(),
)
UNO = GameSpec(
    game_id="uno", rules_version=1, display_name="Uno",
    variant_label="Uno prototype v1 (local rules)", seats=(2, 3, 4),
    tracks=("classic", "model"), protocol=1, adapter=UnoAdapter(),
)
HEARTS = GameSpec(
    game_id="hearts", rules_version=1, display_name="Hearts",
    variant_label="Classic Hearts v1 · single match", seats=(4,),
    tracks=("classic", "model"), protocol=1, adapter=HeartsAdapter(),
)
RUMMY = GameSpec(
    game_id="rummy", rules_version=1, display_name="Rummy 13-card",
    variant_label="Indian Rummy v1 · two decks", seats=(2, 3, 4, 5, 6),
    tracks=("classic", "model"), protocol=1, adapter=RummyAdapter(),
)
HEXCHANGE = GameSpec(
    game_id="hexchange", rules_version=1, display_name="Hexchange",
    variant_label="Hexchange v1 · trading island", seats=(3, 4),
    tracks=("classic", "model"), protocol=1, adapter=HexchangeAdapter(),
)

for _spec in (POKER, BLUFF, UNO, HEARTS, RUMMY, HEXCHANGE):
    # Adapters read their spec for rules blocks; harmless for poker/bluff.
    _spec.adapter.spec = _spec

_GAMES: dict[str, GameSpec] = {
    POKER.game_id: POKER,
    BLUFF.game_id: BLUFF,
    UNO.game_id: UNO,
    HEARTS.game_id: HEARTS,
    RUMMY.game_id: RUMMY,
    HEXCHANGE.game_id: HEXCHANGE,
}


def get_game(game_id: str = "poker", rules_version: int | None = None) -> GameSpec:
    """Resolve a game spec; raise GameError on anything unsupported."""
    if type(game_id) is not str or game_id not in _GAMES:
        raise GameError(f"Unknown game '{game_id}'. Supported: " + ", ".join(sorted(_GAMES)))
    spec = _GAMES[game_id]
    if rules_version is not None and rules_version != spec.rules_version:
        raise GameError(f"Game '{game_id}' supports rules version {spec.rules_version}.")
    return spec


def list_games() -> list[dict]:
    return [spec.public() for spec in _GAMES.values()]
