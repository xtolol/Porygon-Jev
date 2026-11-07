"""Move descriptions reach Jev and telemetry throughout the battle snapshot."""

import asyncio
import json
import logging
from types import SimpleNamespace

import pytest
from poke_env.battle import Battle, Move, Pokemon

from showdown_state_tracer import move_descriptions
from showdown_state_tracer.models import DecisionRecord
from showdown_state_tracer.policies.jev_policy import JevSelectionPolicy
from showdown_state_tracer.snapshot import battle_to_decision_snapshot, move_to_snapshot
from showdown_state_tracer.telemetry import Telemetry
from showdown_state_tracer.tracing_player import TracingRandomPlayer


RECOVER_DESCRIPTION = "Heals the user by 50% of its max HP."


def battle_with_shared_move(generation: int = 9):
    battle = Battle(
        f"battle-gen{generation}randombattle-descriptions", "p1",
        logging.getLogger("descriptions"), generation,
    )
    battle._player_role = "p1"
    active = Pokemon(gen=generation, species="blissey")
    opponent = Pokemon(gen=generation, species="porygon2")
    bench = Pokemon(gen=generation, species="gastrodon")
    active._active = opponent._active = True
    for pokemon in (active, opponent, bench):
        pokemon._moves["recover"] = Move("recover", gen=generation)
    active._moves["toxic"] = Move("toxic", gen=generation)
    battle._team["p1: Blissey"] = active
    battle._team["p1: Gastrodon"] = bench
    battle._opponent_team["p2: Porygon2"] = opponent
    battle._available_moves = [
        Move("recover", gen=generation), Move("toxic", gen=generation),
    ]
    battle._available_switches = [bench]
    return battle


def assert_state_moves_described(state):
    pokemon = [
        state["our_active_pokemon"], state["opponent_active_pokemon"],
        *state["our_team"], *state["opponent_team"],
    ]
    descriptions = {
        "recover": RECOVER_DESCRIPTION,
        "toxic": "Badly poisons the target. Poison types can't miss.",
    }
    for member in pokemon:
        for move in member["moves"]:
            assert move["short_description"] == descriptions[move["id"]]


def test_all_move_descriptions_reach_jev_and_telemetry(tmp_path):
    battle = battle_with_shared_move()
    decision = battle_to_decision_snapshot(battle)
    assert decision.schema_version == 9
    assert [action.id for action in decision.legal_actions] == [
        "move:0:recover", "move:1:toxic", "switch:0:gastrodon",
    ]
    recover = decision.legal_actions[0].move
    assert recover.short_description == RECOVER_DESCRIPTION
    assert recover.heal_fraction == 0.5
    assert decision.legal_actions[1].move.inflicted_status == "TOX"
    assert decision.legal_actions[1].move.short_description == (
        "Badly poisons the target. Poison types can't miss."
    )
    assert move_to_snapshot(battle.available_moves[0]).short_description == RECOVER_DESCRIPTION
    assert move_to_snapshot(
        battle.available_moves[0], short_description="Explicit description",
    ).short_description == "Explicit description"
    assert decision.state.opponent_active_pokemon.moves[0].id == "recover"
    assert decision.state.opponent_active_pokemon.moves[0].short_description == RECOVER_DESCRIPTION
    assert decision.legal_actions[2].switch.moves[0].short_description == RECOVER_DESCRIPTION

    captured = []
    policy = object.__new__(JevSelectionPolicy)

    async def fake_send(payload):
        captured.append(payload)
        return SimpleNamespace(json=lambda: {
            "answers": {"action": {
                "choice": "option_0", "probabilities": {"option_0": 1.0},
                "confidence": 0.8,
            }},
        })

    policy._send_until_success = fake_send
    selection = asyncio.run(policy.select(decision))
    assert selection.action_id == "move:0:recover"
    request = captured[0]
    question = request["questions"]["action"]
    criteria = [json.loads(value) for value in question["criteria"].values()]
    assert criteria[0]["move"]["short_description"] == RECOVER_DESCRIPTION
    assert criteria[2]["switch"]["moves"][0]["short_description"] == RECOVER_DESCRIPTION
    assert "short_description" in question["instructions"]
    assert_state_moves_described(request["state"])

    record = DecisionRecord(
        battle_id=battle.battle_tag, decision_number=1, turn=battle.turn,
        decision=decision, selected_action_id=selection.action_id,
        jev_selected_action_id=selection.action_id, selection_source="jev",
        jev_model=selection.model, jev_confidence=selection.confidence,
        jev_probabilities=selection.probabilities, selected_probability=1.0,
        probability_margin=None,
    )
    path = tmp_path / "decisions.jsonl"
    Telemetry(path).write(record)
    logged = json.loads(path.read_text(encoding="utf-8"))
    assert logged["schema_version"] == 11
    assert logged["decision"]["schema_version"] == 9
    assert logged["selected_action_id"] == "move:0:recover"
    assert logged["decision"]["legal_actions"][0]["move"]["short_description"] == (
        RECOVER_DESCRIPTION
    )
    assert_state_moves_described(logged["decision"]["state"])


@pytest.mark.parametrize(("move_id", "description"), [
    ("recover", RECOVER_DESCRIPTION),
    ("toxic", "Badly poisons the target. Poison types can't miss."),
    ("uturn", "User switches out after damaging the target."),
    ("protect", "Prevents moves from affecting the user this turn."),
    ("stealthrock", "Hurts foes on switch-in. Factors Rock weakness."),
    ("terablast", "If Terastallized: Phys. if Atk > SpA, type = Tera."),
])
def test_each_move_kind_is_described_by_default_and_when_selectable(move_id, description):
    battle = battle_with_shared_move()
    battle._available_moves = [Move(move_id, gen=9)]
    assert move_to_snapshot(battle.available_moves[0]).short_description == description
    decision = battle_to_decision_snapshot(battle)
    assert decision.legal_actions[0].id == f"move:0:{move_id}"
    assert decision.legal_actions[0].move.short_description == description


def test_unsupported_generation_keeps_legal_moves_without_descriptions():
    battle = battle_with_shared_move(generation=8)
    assert move_to_snapshot(battle.available_moves[0]).short_description is None
    decision = battle_to_decision_snapshot(battle)
    assert [action.id for action in decision.legal_actions] == [
        "move:0:recover", "move:1:toxic", "switch:0:gastrodon",
    ]
    assert all(
        action.move.short_description is None
        for action in decision.legal_actions if action.type == "move"
    )


@pytest.mark.parametrize("resource_available", [False, True])
def test_unavailable_description_does_not_remove_legal_actions(
    tmp_path, monkeypatch, resource_available,
):
    if resource_available:
        # A valid but incomplete export can describe one option without the other.
        data = json.loads(
            move_descriptions.files("showdown_state_tracer").joinpath(
                "data", "move_descriptions_gen9.json",
            ).read_text(encoding="utf-8")
        )
        data["moves"] = {"toxic": "Badly poisons the target. Poison types can't miss."}
        resource = tmp_path / "data" / "move_descriptions_gen9.json"
        resource.parent.mkdir()
        resource.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(move_descriptions, "files", lambda package: tmp_path)
    move_descriptions._load_move_descriptions.cache_clear()
    try:
        if resource_available:
            decision = battle_to_decision_snapshot(battle_with_shared_move())
            assert decision.legal_actions[1].move.short_description is not None
        else:
            with pytest.warns(RuntimeWarning, match="Move descriptions unavailable"):
                decision = battle_to_decision_snapshot(battle_with_shared_move())
            assert decision.legal_actions[1].move.short_description is None
        assert [action.id for action in decision.legal_actions] == [
            "move:0:recover", "move:1:toxic", "switch:0:gastrodon",
        ]
        assert decision.legal_actions[0].move.short_description is None
        assert decision.legal_actions[0].move.heal_fraction == 0.5
    finally:
        move_descriptions._load_move_descriptions.cache_clear()


def test_forced_switch_describes_switch_candidate_moves():
    battle = battle_with_shared_move()
    battle._force_switch = True
    battle._available_moves = []

    decision = battle_to_decision_snapshot(battle)
    assert decision.forced_switch is True
    assert [action.id for action in decision.legal_actions] == ["switch:0:gastrodon"]
    assert decision.legal_actions[0].move is None
    assert decision.legal_actions[0].switch.moves[0].short_description == RECOVER_DESCRIPTION


def test_described_actions_still_resolve_to_original_live_orders():
    battle = battle_with_shared_move()
    decision = battle_to_decision_snapshot(battle)
    player = SimpleNamespace(create_order=lambda entry: entry)
    orders = [
        TracingRandomPlayer._action_to_order(player, action, battle)
        for action in decision.legal_actions
    ]
    assert orders[0] is battle.available_moves[0]
    assert orders[1] is battle.available_moves[1]
    assert orders[2] is battle.available_switches[0]
