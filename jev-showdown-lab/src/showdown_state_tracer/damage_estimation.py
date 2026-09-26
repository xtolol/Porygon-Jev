"""Conservative, on-hit damage context for a single active target in Gen 9."""

from math import isfinite

from poke_env.battle import Battle, Move
from poke_env.calc.damage_calc_gen9 import calculate_damage

from showdown_state_tracer.models import DamageEstimate, MoveEffectiveness


# These moves depend on extra conditions or use formulas outside the first scope.
VARIABLE_MOVE_KEYS = {
    "basePowerCallback", "onBasePower", "onModifyMove", "onModifyType"
}
SINGLE_TARGETS = {"NORMAL", "ADJACENT_FOE", "ALL_ADJACENT_FOES"}


def _unavailable(reason: str) -> DamageEstimate:
    return DamageEstimate(None, None, "unknown", None, "unavailable", [reason])


def _has_stats(pokemon) -> bool:
    stats = pokemon.stats
    return all(
        isinstance(stats.get(key), (int, float))
        and isfinite(stats[key])
        and stats[key] > 0
        for key in ("hp", "atk", "def", "spa", "spd")
    )


def _boost_multiplier(stage: int) -> float:
    return (2 + stage) / 2 if stage >= 0 else 2 / (2 - stage)


def _relative_power(move: Move, battle: Battle, matchup: MoveEffectiveness) -> float | None:
    """A unitless same-target comparison, not a predicted damage percentage."""
    attacker = battle.active_pokemon
    defender = battle.opponent_active_pokemon
    attacking_stat = "atk" if move.category.name == "PHYSICAL" else "spa"
    defending_stat = "def" if move.category.name == "PHYSICAL" else "spd"
    attack = attacker.stats.get(attacking_stat) or attacker.base_stats.get(attacking_stat)
    defense = defender.base_stats.get(defending_stat)
    if not isinstance(attack, (int, float)) or not isinstance(defense, (int, float)):
        return None
    if not isfinite(attack) or not isfinite(defense) or attack <= 0 or defense <= 0:
        return None

    attack *= _boost_multiplier(attacker.boosts.get(attacking_stat, 0))
    defense *= _boost_multiplier(defender.boosts.get(defending_stat, 0))
    multiplier = matchup.effectiveness_multiplier
    if multiplier is None:
        return None
    stab = 1.5 if matchup.receives_stab else 1.0
    return round(move.base_power * attack / defense * stab * multiplier, 2)


def estimate_damage(
    move: Move, battle: Battle, matchup: MoveEffectiveness
) -> DamageEstimate | None:
    """Estimate an ordinary move, or explain why only a comparison is available."""
    if move.category.name == "STATUS":
        return None
    if not isinstance(battle, Battle) or battle.gen != 9:
        return _unavailable("Only Gen 9 singles are supported")
    attacker = battle.active_pokemon
    defender = battle.opponent_active_pokemon
    if attacker is None or defender is None:
        return _unavailable("Active attacker or target is unavailable")
    if (
        move.target is None or move.target.name not in SINGLE_TARGETS
        or move.base_power <= 0 or move.damage != 0 or move.n_hit != (1, 1)
        or VARIABLE_MOVE_KEYS.intersection(move.entry)
    ):
        return _unavailable("Variable, fixed, multi-hit, or non-targeted move")

    # The calculator requires known numeric stats. Unknown opponent spreads are
    # common in random battles; do not fabricate a precise HP range for them.
    if _has_stats(attacker) and _has_stats(defender):
        attacker_key = next((k for k, p in battle.team.items() if p is attacker), None)
        defender_key = next((k for k, p in battle.opponent_team.items() if p is defender), None)
        if attacker_key and defender_key:
            try:
                minimum, maximum = calculate_damage(
                    attacker_key, defender_key, move, battle
                )
                hp = defender.stats["hp"]
                if not all(isfinite(x) and x >= 0 for x in (minimum, maximum)):
                    raise ValueError("Invalid damage range")
                minimum, maximum = sorted((minimum, maximum))
                current_hp = defender.current_hp_fraction * hp
                outlook = (
                    "guaranteed" if minimum >= current_hp
                    else "possible" if maximum >= current_hp else "unlikely"
                )
                return DamageEstimate(
                    min_hp_fraction=round(minimum / hp, 4),
                    max_hp_fraction=round(maximum / hp, 4),
                    on_hit_ko_outlook=outlook,
                    relative_power=None,
                    source="poke_env_gen9",
                    assumptions=[
                        "Conditional on the recorded stats, item, ability and battle state",
                        "On-hit, non-critical range; accuracy and opponent actions are separate",
                        "poke-env calculator does not cover every mechanic",
                    ],
                )
            except (
                AssertionError, AttributeError, KeyError, TypeError,
                ValueError, ZeroDivisionError, OverflowError, NotImplementedError,
            ):
                # Fall back to a comparison; never turn an incomplete calc into
                # a deceptively precise range.
                pass

    score = _relative_power(move, battle, matchup)
    if score is None:
        return _unavailable("Insufficient data for even a relative comparison")
    return DamageEstimate(
        min_hp_fraction=None,
        max_hp_fraction=None,
        on_hit_ko_outlook="unknown",
        relative_power=score,
        source="relative_power",
        assumptions=[
            "Compare only ordinary moves against this same target",
            "Uses base defense when opponent stats are unknown",
            "Omits items, abilities, weather, burn and other power modifiers",
            "Accuracy is separate; this is not a damage fraction or KO chance",
        ],
    )
