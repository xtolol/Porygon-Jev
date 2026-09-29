"""Per-switch type context reaches Jev without inventing opponent moves."""

import asyncio
import json
import logging
from dataclasses import asdict
from types import SimpleNamespace

from poke_env.battle import Battle, Move, Pokemon, SideCondition

from showdown_state_tracer.models import ActionMemorySnapshot
from showdown_state_tracer.policies.jev_policy import JevSelectionPolicy
from showdown_state_tracer.snapshot import battle_to_decision_snapshot
from showdown_state_tracer.switch_context import annotate_switch


def battle_with_switches():
    battle = Battle("battle-gen9randombattle-switch", "p1", logging.getLogger("switch"), 9)
    battle._player_role = "p1"
    active = Pokemon(gen=9, species="ursaluna")
    opponent = Pokemon(gen=9, species="electrode")
    gastrodon = Pokemon(gen=9, species="gastrodon")
    gyarados = Pokemon(gen=9, species="gyarados")
    active._active = opponent._active = True
    active._boosts["atk"] = 2
    opponent._moves["thunderbolt"] = Move("thunderbolt", gen=9)
    opponent._moves["thunderwave"] = Move("thunderwave", gen=9)
    gastrodon._moves["earthpower"] = Move("earthpower", gen=9)
    gyarados._moves["waterfall"] = Move("waterfall", gen=9)
    battle._team["p1: Ursaluna"] = active
    battle._team["p1: Gastrodon"] = gastrodon
    battle._team["p1: Gyarados"] = gyarados
    battle._opponent_team["p2: Electrode"] = opponent
    battle._available_moves = [Move("earthquake", gen=9)]
    battle._available_switches = [gastrodon, gyarados]
    battle._side_conditions[SideCondition.STEALTH_ROCK] = 1
    battle._side_conditions[SideCondition.SPIKES] = 2
    return battle


def switch(decision, species):
    return next(
        option for option in decision.legal_actions
        if option.type == "switch" and option.switch.species == species
    )


def test_each_legal_switch_gets_distinct_type_and_entry_context():
    battle = battle_with_switches()
    decision = battle_to_decision_snapshot(battle)
    gastrodon = switch(decision, "gastrodon").switch_context
    gyarados = switch(decision, "gyarados").switch_context

    assert decision.schema_version == 5
    assert decision.legal_actions[0].switch_context is None
    assert [(m.source, m.multiplier) for m in gastrodon.revealed_move_matchups] == [
        ("thunderbolt", 0)
    ]
    assert [(m.source, m.multiplier) for m in gyarados.revealed_move_matchups] == [
        ("thunderbolt", 4)
    ]
    assert all(m.source != "thunderwave" for m in gastrodon.revealed_move_matchups)
    assert [(m.source, m.multiplier) for m in gastrodon.possible_stab_matchups] == [
        ("ELECTRIC", 0)
    ]
    assert gastrodon.offensive_move_matchups[0].source == "earthpower"
    assert gastrodon.offensive_move_matchups[0].multiplier == 2
    assert [h.name for h in gastrodon.entry_hazards] == ["STEALTH_ROCK", "SPIKES"]
    assert gastrodon.entry_hazards[1].layers == 2
    assert gyarados.entry_hazards[1].exposure == "uncertain"
    assert "2x" in gyarados.entry_hazards[0].reason
    assert gastrodon.active_boosts_lost == {"atk": 2}
    assert gastrodon.last_action_was_switch is None
    assert not gastrodon.forced_switch


def test_unknown_moves_remain_unknown_and_boots_are_per_candidate():
    battle = battle_with_switches()
    battle.opponent_active_pokemon._moves._base_moves.clear()
    battle.available_switches[0]._item = "heavydutyboots"
    decision = battle_to_decision_snapshot(battle)
    gastrodon = switch(decision, "gastrodon").switch_context
    gyarados = switch(decision, "gyarados").switch_context

    assert gastrodon.revealed_move_matchups == []
    assert gastrodon.possible_stab_matchups[0].source == "ELECTRIC"
    assert all(h.exposure == "blocked_by_boots" for h in gastrodon.entry_hazards)
    assert gyarados.entry_hazards[0].exposure == "present"


def test_forced_switch_and_existing_history_are_annotations_not_mutations():
    battle = battle_with_switches()
    battle._force_switch = True
    history = [ActionMemorySnapshot(
        turn=2, action_id="switch:0:Gastrodon", actor_species="Ursaluna",
        target_species=None, target_hp_before=None, target_hp_after=None,
        damage_fraction=None, outcome="switch_selected", known_target_ability=None,
    )]
    decision = battle_to_decision_snapshot(battle, history)
    state_before = asdict(decision.state)
    candidate_before = asdict(switch(decision, "gyarados").switch)
    context = annotate_switch(
        decision.state, switch(decision, "gyarados").switch,
        history, True, battle.gen,
    )

    assert context.forced_switch
    assert context.last_action_was_switch
    assert asdict(decision.state) == state_before
    assert asdict(switch(decision, "gyarados").switch) == candidate_before


def test_switch_context_is_sent_with_the_legal_option_to_jev():
    decision = battle_to_decision_snapshot(battle_with_switches())
    policy = object.__new__(JevSelectionPolicy)
    payloads = []

    async def fake_send(payload):
        payloads.append(payload)
        return SimpleNamespace(json=lambda: {
            "answers": {"action": {
                "choice": "option_1",
                "probabilities": {"option_0": 0.1, "option_1": 0.8, "option_2": 0.1},
            }},
        })

    policy._send_until_success = fake_send
    selected = asyncio.run(policy.select(decision))
    option = json.loads(payloads[0]["questions"]["action"]["criteria"]["option_1"])

    assert selected.action_id == "switch:0:gastrodon"
    assert option["switch_context"]["revealed_move_matchups"][0]["multiplier"] == 0
    assert option["switch_context"]["entry_hazards"][0]["name"] == "STEALTH_ROCK"
    assert option["switch_context"]["active_boosts_lost"] == {"atk": 2}
    assert "not damage or survival predictions" in (
        payloads[0]["questions"]["action"]["instructions"]
    )
