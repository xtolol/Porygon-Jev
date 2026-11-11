import asyncio
from collections import defaultdict
from dataclasses import dataclass
import random
from types import SimpleNamespace

import pytest

from showdown_state_tracer.battle_memory import BattleMemory
from showdown_state_tracer.models import ActionOption, DecisionSnapshot
from showdown_state_tracer.policies.jev_policy import JevSelectionPolicy
from showdown_state_tracer.tracing_player import TracingRandomPlayer


def battle(tag="battle-1", hp=1.0):
    target = SimpleNamespace(species="Electrode", current_hp_fraction=hp, ability=None)
    active = SimpleNamespace(species="Ursaluna", current_hp_fraction=0.8)
    pivot = SimpleNamespace(species="Skeledirge", current_hp_fraction=1.0)
    return SimpleNamespace(
        battle_tag=tag,
        turn=1,
        active_pokemon=active,
        team={"p1: Ursaluna": active, "p1: Skeledirge": pivot},
        available_switches=[pivot],
        force_switch=False,
        opponent_active_pokemon=target,
        opponent_team={"p2: Electrode": target},
    )


MOVE = ActionOption(id="move:0:hypervoice", type="move")
SWITCH = ActionOption(id="switch:0:skeledirge", type="switch")


@pytest.mark.parametrize(
    ("after", "expected", "damage"),
    [
        (0.6, "damage_observed", 0.4),
        (1.0, "no_net_damage_observed", None),
    ],
)
def test_resolves_target_hp_without_claiming_immunity(after, expected, damage):
    memory = BattleMemory()
    state = battle()
    memory.remember(state, MOVE)
    state.turn += 1
    state.opponent_active_pokemon.current_hp_fraction = after

    observed = memory.resolve(state)

    assert observed.outcome == expected
    if damage is None:
        assert observed.damage_fraction is None
    else:
        assert observed.damage_fraction == pytest.approx(damage)
    assert observed.target_species == "Electrode"
    assert memory.resolve(state) is None


def test_tracks_same_target_after_switch_and_revealed_ability():
    memory = BattleMemory()
    state = battle(hp=0.5)
    memory.remember(state, MOVE)
    old_target = state.opponent_active_pokemon
    old_target.current_hp_fraction = 0.8
    old_target.ability = "soundproof"
    state.opponent_active_pokemon = SimpleNamespace(species="Mandibuzz")

    observed = memory.resolve(state)

    assert observed.outcome == "target_recovered"
    assert observed.target_hp_after == 0.8
    assert observed.known_target_ability == "soundproof"


def test_unavailable_target_and_three_entry_limit_are_per_battle():
    memory = BattleMemory()
    first = battle()
    second = battle(tag="battle-2")
    memory.remember(second, MOVE)
    for turn in range(1, 5):
        first.turn = turn
        memory.remember(first, MOVE)
        memory.resolve(first)

    assert [entry.turn for entry in memory.recent_actions(first.battle_tag)] == [2, 3, 4]
    assert memory.recent_actions(second.battle_tag) == []
    second.opponent_team.clear()
    assert memory.resolve(second).outcome == "target_unavailable"
    memory.clear(first.battle_tag)
    assert memory.recent_actions(first.battle_tag) == []
    assert len(memory.recent_actions(second.battle_tag)) == 1


def test_switch_observation_has_no_target_hp():
    memory = BattleMemory()
    state = battle()
    memory.remember(state, SWITCH)
    observed = memory.resolve(state)
    assert (observed.outcome, observed.target_hp_before, observed.damage_fraction) == (
        "switch_selected", None, None
    )
    assert observed.switch_from_species == "Ursaluna"
    assert observed.switch_to_species == "Skeledirge"
    assert observed.forced_switch is False
    assert observed.switch_in_hp_before == 1.0
    assert observed.switch_in_hp_after == 1.0


def test_forced_switch_and_net_entry_hp_are_recorded_without_damage_attribution():
    memory = BattleMemory()
    state = battle()
    state.force_switch = True
    memory.remember(state, SWITCH)
    state.team["p1: Skeledirge"].current_hp_fraction = 0.75
    observed = memory.resolve(state)
    assert observed.forced_switch is True
    assert observed.switch_in_hp_before == 1.0
    assert observed.switch_in_hp_after == 0.75
    assert observed.damage_fraction is None


def test_opponent_events_preserve_repeats_switches_and_battle_isolation():
    memory = BattleMemory()
    for turn in range(1, 6):
        memory.observe_opponent_event("battle-1", turn, "electrode", "move", move_id="Thunderbolt")
    memory.observe_opponent_event("battle-1", 5, "electrode", "switch", switch_to_species="mandibuzz")
    memory.observe_opponent_event("battle-1", 6, "mandibuzz", "move", move_id="U-turn")
    memory.observe_opponent_event("battle-2", 1, "pikachu", "move", move_id="Thunderbolt")
    history = memory.recent_opponent_actions("battle-1")
    assert len(history) == 6
    assert [event.move_id for event in history[:4]] == ["thunderbolt"] * 4
    assert (history[-2].action_type, history[-2].switch_to_species) == ("switch", "mandibuzz")
    assert history[-1].move_id == "uturn"
    memory.clear("battle-1")
    assert memory.recent_opponent_actions("battle-1") == []
    assert len(memory.recent_opponent_actions("battle-2")) == 1


def test_protocol_batch_reaches_memory_before_request_and_tracks_pivot(monkeypatch):
    from poke_env.player import RandomPlayer

    state = battle(tag="battle-gen9randombattle-123")
    state.player_role = "p1"
    player = object.__new__(TracingRandomPlayer)
    player._memory = BattleMemory()
    player._battles = {state.battle_tag: state}
    seen_at_request = []

    async def handle_batch(self, messages):
        seen_at_request.extend(self._memory.recent_opponent_actions(state.battle_tag))

    monkeypatch.setattr(RandomPlayer, "_handle_battle_message", handle_batch)
    messages = [
        [">" + state.battle_tag],
        ["", "turn", "2"],
        ["", "move", "p2a: Electrode", "Thunderbolt", "p1a: Ursaluna"],
        ["", "move", "p2a: Electrode", "Thunderbolt", "p1a: Ursaluna"],
        ["", "switch", "p2a: Mandibuzz", "Mandibuzz, L85", "100/100"],
        ["", "move", "p2a: Mandibuzz", "U-turn", "p1a: Ursaluna"],
        ["", "switch", "p2a: Electrode", "Electrode, L85", "100/100"],
        ["", "request", "{}"],
    ]
    asyncio.run(player._handle_battle_message(messages))
    assert [(a.turn, a.action_type, a.actor_species, a.move_id, a.switch_to_species)
            for a in seen_at_request] == [
        (2, "move", "Electrode", "thunderbolt", None),
        (2, "move", "Electrode", "thunderbolt", None),
        (2, "switch", "Electrode", None, "mandibuzz"),
        (2, "move", "mandibuzz", "uturn", None),
        (2, "switch", "mandibuzz", None, "electrode"),
    ]


def test_player_passes_resolved_history_and_records_fallback(monkeypatch):
    import showdown_state_tracer.tracing_player as module

    decisions = []

    def make_decision(state, recent_actions, recent_opponent_actions):
        return DecisionSnapshot(
            state=state, legal_actions=[MOVE], forced_switch=False,
            recent_actions=recent_actions,
            recent_opponent_actions=recent_opponent_actions,
        )

    monkeypatch.setattr(module, "battle_to_decision_snapshot", make_decision)

    class FailedPolicy:
        async def select(self, decision):
            raise RuntimeError("gateway unavailable")

    player = object.__new__(TracingRandomPlayer)
    player.selection_policy = FailedPolicy()
    player.random = random.Random(1)
    player._decision_counts = defaultdict(int)
    player._memory = BattleMemory()
    player.trace_writer = SimpleNamespace(write=decisions.append)
    player._action_to_order = lambda action, state: action.id
    state = battle()

    assert asyncio.run(player.choose_move(state)) == MOVE.id
    state.turn = 2
    assert asyncio.run(player.choose_move(state)) == MOVE.id
    assert decisions[0].selection_source == "random_fallback"
    assert decisions[0].selected_probability is None
    assert decisions[1].decision.recent_actions[0].outcome == "no_net_damage_observed"
    player._battle_finished_callback(state)
    assert player._memory.recent_actions(state.battle_tag) == []
    assert player._memory.recent_opponent_actions(state.battle_tag) == []
    assert state.battle_tag not in player._decision_counts


def test_jev_payload_contains_shared_memory():
    @dataclass
    class State:
        battle_tag: str = "battle-1"

    memory = BattleMemory()
    state = battle()
    memory.remember(state, MOVE)
    memory.observe_opponent_event(state.battle_tag, 1, "electrode", "move", move_id="Thunderbolt")
    decision = DecisionSnapshot(
        state=State(), legal_actions=[MOVE], forced_switch=False,
        recent_actions=[memory.resolve(state)],
        recent_opponent_actions=memory.recent_opponent_actions(state.battle_tag),
    )
    policy = object.__new__(JevSelectionPolicy)
    payloads = []

    async def fake_send(payload):
        payloads.append(payload)
        return SimpleNamespace(json=lambda: {
            "answers": {"action": {"choice": "option_0", "probabilities": {"option_0": 1.0}}}
        })

    policy._send_until_success = fake_send
    result = asyncio.run(policy.select(decision))

    assert result.action_id == MOVE.id
    assert payloads[0]["state"]["recent_actions"][0]["outcome"] == "no_net_damage_observed"
    assert payloads[0]["state"]["recent_opponent_actions"][0]["move_id"] == "thunderbolt"
