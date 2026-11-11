"""Known ability and item descriptions reach Jev and versioned telemetry."""

import asyncio
from dataclasses import asdict
import json
import logging
from types import SimpleNamespace

from poke_env.battle import Battle, Move, Pokemon

from showdown_state_tracer.models import DecisionRecord
from showdown_state_tracer.policies.jev_policy import JevSelectionPolicy
from showdown_state_tracer.snapshot import battle_to_decision_snapshot, pokemon_to_snapshot
from showdown_state_tracer.telemetry import Telemetry


EXPECTED = {
    "slowbro": {
        "ability": "regenerator",
        "ability_short_description": (
            "This Pokemon restores 1/3 of its maximum HP, rounded down, when it switches out."
        ),
        "item": "leftovers",
        "item_short_description": "At the end of every turn, holder restores 1/16 of its max HP.",
    },
    "electrode": {
        "ability": "soundproof",
        "ability_short_description": (
            "This Pokemon is immune to sound-based moves, unless it used the move."
        ),
        "item": "choicescarf",
        "item_short_description": (
            "Holder's Speed is 1.5×, but it can only select the first move it executes."
        ),
    },
    "gyarados": {
        "ability": "intimidate",
        "ability_short_description": (
            "On switch-in, this Pokemon lowers the Attack of opponents by 1 stage."
        ),
        "item": "heavydutyboots",
        "item_short_description": (
            "When switching in, the holder is unaffected by hazards on its side of the field."
        ),
    },
}


def battle_with_known_attributes():
    battle = Battle(
        "battle-gen9randombattle-attributes", "p1", logging.getLogger("attributes"), 9,
    )
    battle._player_role = "p1"
    ours = Pokemon(gen=9, species="slowbro")
    opponent = Pokemon(gen=9, species="electrode")
    bench = Pokemon(gen=9, species="gyarados")
    ours._active = opponent._active = True
    for pokemon in (ours, opponent, bench):
        attributes = EXPECTED[pokemon.species]
        pokemon.ability = attributes["ability"]
        pokemon.item = attributes["item"]
    ours._moves["surf"] = Move("surf", gen=9)
    bench._moves["waterfall"] = Move("waterfall", gen=9)
    battle._team["p1: Slowbro"] = ours
    battle._team["p1: Gyarados"] = bench
    battle._opponent_team["p2: Electrode"] = opponent
    battle._available_moves = [Move("surf", gen=9)]
    battle._available_switches = [bench]
    return battle


def assert_pokemon_described(pokemon):
    for field, expected in EXPECTED[pokemon["species"]].items():
        assert pokemon[field] == expected


def assert_state_described(state):
    for pokemon in [
        state["our_active_pokemon"], state["opponent_active_pokemon"],
        *state["our_team"], *state["opponent_team"],
    ]:
        assert_pokemon_described(pokemon)


def test_known_attributes_reach_all_snapshots_jev_and_telemetry(tmp_path):
    battle = battle_with_known_attributes()
    # Direct conversion uses the same automatic lookup as battle construction.
    assert_pokemon_described(asdict(pokemon_to_snapshot(battle.active_pokemon)))
    decision = battle_to_decision_snapshot(battle)
    assert decision.schema_version == 9
    assert [action.id for action in decision.legal_actions] == [
        "move:0:surf", "switch:0:gyarados",
    ]
    assert_state_described(asdict(decision.state))
    assert_pokemon_described(asdict(decision.legal_actions[1].switch))

    captured = []
    policy = object.__new__(JevSelectionPolicy)

    async def fake_send(payload):
        captured.append(payload)
        return SimpleNamespace(json=lambda: {
            "answers": {"action": {
                "choice": "option_1", "probabilities": {"option_0": 0.1, "option_1": 0.9},
                "confidence": 0.8,
            }},
        })

    policy._send_until_success = fake_send
    selection = asyncio.run(policy.select(decision))
    assert selection.action_id == "switch:0:gyarados"
    request = captured[0]
    assert_state_described(request["state"])
    question = request["questions"]["action"]
    switch = json.loads(question["criteria"]["option_1"])
    assert_pokemon_described(switch["switch"])
    assert "ability_short_description" in question["instructions"]
    assert "item_short_description" in question["instructions"]

    record = DecisionRecord(
        battle_id=battle.battle_tag, decision_number=1, turn=battle.turn,
        decision=decision, selected_action_id=selection.action_id,
        jev_selected_action_id=selection.action_id, selection_source="jev",
        jev_model=selection.model, jev_confidence=selection.confidence,
        jev_probabilities=selection.probabilities, selected_probability=0.9,
        probability_margin=0.8,
    )
    path = tmp_path / "decisions.jsonl"
    Telemetry(path).write(record)
    logged = json.loads(path.read_text(encoding="utf-8"))
    assert logged["schema_version"] == 11
    assert logged["decision"]["schema_version"] == 9
    assert logged["selected_action_id"] == "switch:0:gyarados"
    assert_state_described(logged["decision"]["state"])
    assert_pokemon_described(logged["decision"]["legal_actions"][1]["switch"])
