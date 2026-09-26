"""Ability evidence is present in the decision and Jev choice request."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from poke_env.battle import Move

from showdown_state_tracer.policies.jev_policy import JevSelectionPolicy
from showdown_state_tracer.snapshot import battle_to_decision_snapshot, move_to_snapshot


def pokemon(species, ability=None):
    return SimpleNamespace(
        types=[], species=species, level=100, item=None, ability=ability,
        status=None, moves={}, current_hp_fraction=1.0, boosts={}, active=True,
        fainted=False, revealed=True, damage_multiplier=lambda move: 1.0,
    )


def decision_for(ability):
    ours = pokemon("Ursaluna")
    opponent = pokemon("Electrode", ability)
    battle = SimpleNamespace(
        battle_tag="battle-soundproof", format="gen9randombattle", turn=5,
        active_pokemon=ours, team={"p1: Ursaluna": ours},
        opponent_active_pokemon=opponent, opponent_team={"p2: Electrode": opponent},
        weather={}, fields={}, side_conditions={}, opponent_side_conditions={},
        finished=False, won=None, force_switch=False,
        available_moves=[Move("hypervoice", gen=9), Move("earthpower", gen=9)],
        available_switches=[],
    )
    return battle_to_decision_snapshot(battle)


async def jev_payload(decision):
    captured = []
    policy = object.__new__(JevSelectionPolicy)

    async def fake_send(payload):
        captured.append(payload)
        return SimpleNamespace(json=lambda: {
            "answers": {"action": {
                "choice": "option_1", "probabilities": {"option_0": 0.1, "option_1": 0.9}
            }}
        })

    policy._send_until_success = fake_send
    selection = await policy.select(decision)
    assert selection.action_id == "move:1:earthpower"
    return captured[0]


@pytest.mark.parametrize("ability", ["soundproof", None])
def test_ability_and_flags_reach_jev_without_claiming_a_block(ability):
    decision = decision_for(ability)
    assert decision.state.opponent_active_pokemon.ability == ability
    payload = asyncio.run(jev_payload(decision))
    criteria = payload["questions"]["action"]["criteria"]
    hyper_voice = json.loads(criteria["option_0"])["move"]
    earth_power = json.loads(criteria["option_1"])["move"]

    assert payload["state"]["opponent_active_pokemon"]["ability"] == ability
    assert "sound" in hyper_voice["move_flags"]
    assert hyper_voice["move_flags"] == sorted(hyper_voice["move_flags"])
    assert hyper_voice["ignore_ability"] is False
    assert "sound" not in earth_power["move_flags"]
    assert "known_ability_block" not in json.loads(criteria["option_0"])
    assert "revealed ability" in payload["questions"]["action"]["instructions"]


def test_ignore_ability_is_read_from_poke_env():
    move = Move("gmaxdrumsolo", gen=9)
    assert move_to_snapshot(move).ignore_ability is True
