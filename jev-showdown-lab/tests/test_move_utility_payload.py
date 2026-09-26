"""Utility information survives move conversion and the Jev request builder."""

import asyncio
import json
from dataclasses import dataclass
from types import SimpleNamespace

from poke_env.battle import Move

from showdown_state_tracer.models import ActionOption, DecisionSnapshot
from showdown_state_tracer.policies.jev_policy import JevSelectionPolicy
from showdown_state_tracer.snapshot import move_to_snapshot


@dataclass
class State:
    battle_tag: str = "battle-utility"


def criteria_for(*moves):
    decision = DecisionSnapshot(
        state=State(),
        legal_actions=[
            ActionOption(id=f"move:{index}:{move.id}", type="move", move=move_to_snapshot(move))
            for index, move in enumerate(moves)
        ],
        forced_switch=False,
    )
    captured = []
    policy = object.__new__(JevSelectionPolicy)

    async def fake_send(payload):
        captured.append(payload)
        return SimpleNamespace(json=lambda: {
            "answers": {"action": {
                "choice": "option_0", "probabilities": {"option_0": 1.0}
            }}
        })

    policy._send_until_success = fake_send
    selection = asyncio.run(policy.select(decision))
    assert selection.action_id == decision.legal_actions[0].id
    return [json.loads(value) for value in captured[0]["questions"]["action"]["criteria"].values()]


def test_self_target_boost_and_self_penalty_reach_jev():
    calm_mind, close_combat = criteria_for(Move("calmmind", gen=9), Move("closecombat", gen=9))
    assert calm_mind["move"]["boosts"] == {"spa": 1, "spd": 1}
    assert calm_mind["move"]["self_boosts"] == {"spa": 1, "spd": 1}
    assert close_combat["move"]["boosts"] is None
    assert close_combat["move"]["self_boosts"] == {"def": -1, "spd": -1}


def test_healing_and_status_reach_jev():
    recover, toxic = criteria_for(Move("recover", gen=9), Move("toxic", gen=9))
    assert recover["move"]["heal_fraction"] == 0.5
    assert recover["move"]["inflicted_status"] is None
    assert toxic["move"]["heal_fraction"] == 0.0
    assert toxic["move"]["inflicted_status"] == "TOX"


def test_opponent_target_boost_is_not_self_boost():
    growl = move_to_snapshot(Move("growl", gen=9))
    assert growl.boosts == {"atk": -1}
    assert growl.self_boosts is None
