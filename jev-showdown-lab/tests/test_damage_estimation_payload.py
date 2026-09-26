"""Damage context from a Gen 9 battle reaches Jev's legal-action criteria."""

import asyncio
import json
import logging
from types import SimpleNamespace

import pytest
from poke_env.battle import Battle, Move, Pokemon

from showdown_state_tracer.policies.jev_policy import JevSelectionPolicy
from showdown_state_tracer.snapshot import battle_to_decision_snapshot


def battle_with_moves(*names, known_target_stats=True, ability=None):
    battle = Battle("battle-gen9ou-damage", "p1", logging.getLogger("damage-test"), 9)
    battle._player_role = "p1"
    attacker = Pokemon(gen=9, species="ursaluna")
    target = Pokemon(gen=9, species="electrode")
    attacker._active = target._active = True
    attacker._stats = {
        "hp": 400, "atk": 300, "def": 200, "spa": 250, "spd": 200, "spe": 130
    }
    attacker._max_hp = attacker._current_hp = 400
    if known_target_stats:
        target._stats = {
            "hp": 260, "atk": 150, "def": 160, "spa": 200, "spd": 180, "spe": 300
        }
        target._max_hp = target._current_hp = 260
    else:
        # A visible percentage does not reveal an opponent's actual stats.
        target._max_hp = target._current_hp = 100
    target._ability = ability
    battle._team["p1: Ursaluna"] = attacker
    battle._opponent_team["p2: Electrode"] = target
    battle._available_moves = [Move(name, gen=9) for name in names]
    return battle


def option(decision, move_id):
    return next(action for action in decision.legal_actions if action.move.id == move_id)


def test_known_stats_produce_conditional_on_hit_range_and_ko_outlook():
    decision = battle_to_decision_snapshot(battle_with_moves("earthpower", "hypervoice"))
    earth_power = option(decision, "earthpower").damage_estimate
    hyper_voice = option(decision, "hypervoice").damage_estimate

    assert decision.schema_version == 5
    assert earth_power.source == "poke_env_gen9"
    assert earth_power.min_hp_fraction == pytest.approx(270 / 260, abs=1e-4)
    assert earth_power.max_hp_fraction == pytest.approx(320 / 260, abs=1e-4)
    assert earth_power.on_hit_ko_outlook == "guaranteed"
    assert hyper_voice.on_hit_ko_outlook == "unlikely"


def test_unknown_opponent_stats_produce_only_relative_comparison():
    decision = battle_to_decision_snapshot(
        battle_with_moves("earthpower", "hypervoice", known_target_stats=False)
    )
    earth_power = option(decision, "earthpower").damage_estimate
    hyper_voice = option(decision, "hypervoice").damage_estimate

    assert earth_power.source == hyper_voice.source == "relative_power"
    assert earth_power.relative_power > hyper_voice.relative_power > 0
    assert earth_power.min_hp_fraction is earth_power.max_hp_fraction is None
    assert earth_power.on_hit_ko_outlook == "unknown"
    assert any("base defense" in text for text in earth_power.assumptions)


def test_relative_comparison_reflects_our_known_stat_boosts():
    battle = battle_with_moves("earthpower", known_target_stats=False)
    initial = battle_to_decision_snapshot(battle).legal_actions[0].damage_estimate
    battle.active_pokemon._boosts["spa"] = 2
    boosted = battle_to_decision_snapshot(battle).legal_actions[0].damage_estimate
    assert boosted.relative_power == pytest.approx(initial.relative_power * 2, abs=0.01)


def test_unsupported_moves_and_switches_do_not_claim_damage():
    battle = battle_with_moves("calmmind", "hex", "doublehit")
    switch = Pokemon(gen=9, species="skeledirge")
    battle._team["p1: Skeledirge"] = switch
    battle._available_switches = [switch]
    decision = battle_to_decision_snapshot(battle)

    assert option(decision, "calmmind").damage_estimate is None
    assert option(decision, "hex").damage_estimate.source == "unavailable"
    assert option(decision, "doublehit").damage_estimate.source == "unavailable"
    assert decision.legal_actions[-1].type == "switch"
    assert decision.legal_actions[-1].damage_estimate is None


def test_known_soundproof_calculator_range_is_zero():
    decision = battle_to_decision_snapshot(
        battle_with_moves("hypervoice", ability="soundproof")
    )
    estimate = decision.legal_actions[0].damage_estimate
    assert estimate.source == "poke_env_gen9"
    assert estimate.min_hp_fraction == estimate.max_hp_fraction == 0
    assert estimate.on_hit_ko_outlook == "unlikely"


def test_jev_payload_contains_estimates_and_keeps_accuracy_separate():
    decision = battle_to_decision_snapshot(
        battle_with_moves("earthpower", "hypervoice", known_target_stats=False)
    )
    payloads = []
    policy = object.__new__(JevSelectionPolicy)

    async def fake_send(payload):
        payloads.append(payload)
        return SimpleNamespace(json=lambda: {
            "answers": {"action": {
                "choice": "option_0", "probabilities": {"option_0": 0.7, "option_1": 0.3}
            }}
        })

    policy._send_until_success = fake_send
    selected = asyncio.run(policy.select(decision))
    earth_power = json.loads(payloads[0]["questions"]["action"]["criteria"]["option_0"])
    assert selected.action_id == "move:0:earthpower"
    assert earth_power["damage_estimate"]["source"] == "relative_power"
    assert earth_power["damage_estimate"]["on_hit_ko_outlook"] == "unknown"
    assert earth_power["move"]["accuracy"] is not None
    assert "not an HP percentage" in payloads[0]["questions"]["action"]["instructions"]
