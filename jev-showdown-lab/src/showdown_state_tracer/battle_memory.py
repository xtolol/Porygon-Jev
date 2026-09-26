"""Short-term observations of actions selected in each battle."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from showdown_state_tracer.models import ActionMemorySnapshot, ActionOption

if TYPE_CHECKING:
    from poke_env.battle import Battle


@dataclass(frozen=True, slots=True)
class _PendingAction:
    turn: int
    action_id: str
    action_type: str
    actor_species: str | None
    target_key: str | None
    target_species: str | None
    target_hp_before: float | None
    known_target_ability: str | None


@dataclass(slots=True)
class _BattleHistory:
    pending: _PendingAction | None = None
    recent: deque[ActionMemorySnapshot] = field(
        default_factory=lambda: deque(maxlen=3)
    )


class BattleMemory:
    def __init__(self) -> None:
        self._battles: dict[str, _BattleHistory] = {}

    def remember(self, battle: Battle, action: ActionOption) -> None:
        """Record the order we are about to return, before Showdown plays it."""
        target = battle.opponent_active_pokemon if action.type == "move" else None
        target_key = next(
            (
                key
                for key, pokemon in battle.opponent_team.items()
                if pokemon is target
            ),
            None,
        )
        self._battles.setdefault(battle.battle_tag, _BattleHistory()).pending = (
            _PendingAction(
                turn=battle.turn,
                action_id=action.id,
                action_type=action.type,
                actor_species=(
                    battle.active_pokemon.species if battle.active_pokemon else None
                ),
                target_key=target_key,
                target_species=target.species if target else None,
                target_hp_before=target.current_hp_fraction if target else None,
                known_target_ability=target.ability if target else None,
            )
        )

    def resolve(self, battle: Battle) -> ActionMemorySnapshot | None:
        """Compare the pending target with the next updated battle state."""
        history = self._battles.get(battle.battle_tag)
        if history is None or history.pending is None:
            return None

        pending = history.pending
        history.pending = None
        target = (
            battle.opponent_team.get(pending.target_key)
            if pending.target_key is not None
            else None
        )
        hp_after = target.current_hp_fraction if target else None
        damage = None

        if pending.action_type == "switch":
            outcome = "switch_selected"
        elif hp_after is None or pending.target_hp_before is None:
            outcome = "target_unavailable"
        elif hp_after < pending.target_hp_before - 1e-6:
            outcome = "damage_observed"
            damage = pending.target_hp_before - hp_after
        elif hp_after > pending.target_hp_before + 1e-6:
            outcome = "target_recovered"
        else:
            outcome = "no_net_damage_observed"

        observation = ActionMemorySnapshot(
            turn=pending.turn,
            action_id=pending.action_id,
            actor_species=pending.actor_species,
            target_species=pending.target_species,
            target_hp_before=pending.target_hp_before,
            target_hp_after=hp_after,
            damage_fraction=damage,
            outcome=outcome,
            known_target_ability=(
                target.ability
                if target and target.ability
                else pending.known_target_ability
            ),
        )
        history.recent.append(observation)
        return observation

    def recent_actions(self, battle_tag: str) -> list[ActionMemorySnapshot]:
        history = self._battles.get(battle_tag)
        return list(history.recent) if history else []

    def clear(self, battle_tag: str) -> None:
        self._battles.pop(battle_tag, None)
