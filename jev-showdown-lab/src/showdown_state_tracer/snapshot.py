from poke_env.battle import Move
from poke_env.battle.pokemon import Pokemon
from showdown_state_tracer.models import MoveSnapshot, PokemonSnapshot, FieldSnapshot, BattleSnapshot, ActionOption, DecisionSnapshot
from enum import Enum
from collections.abc import Mapping
from poke_env.battle import Battle


def _snapshot_to_dict(effects: Mapping[Enum, int]) -> dict[str, int]:
    return {
        effect.name: value
        for effect, value in sorted(effects.items(), key=lambda item: item[0].name
        )
    }
def move_to_snapshot(move: Move) -> MoveSnapshot:
    return MoveSnapshot(
        id=move.id,
        name=move.entry.get("name", move.id),
        type=move.type.name if move.type is not None else None,
        category=move.category.name if move.category is not None else None,
        base_power=move.base_power,
        accuracy=move.accuracy,
        priority=move.priority,
        current_pp=move.current_pp,
        max_pp=move.max_pp,
        is_protect_move=move.is_protect_move,
        boosts=move.boosts,
        target=move.target.name if move.target is not None else None
    )
    
def pokemon_to_snapshot(pokemon: Pokemon) -> PokemonSnapshot:
    return PokemonSnapshot(
        types=[t.name for t in pokemon.types],
        species=pokemon.species,
        level=pokemon.level,
        item=pokemon.item,
        ability=pokemon.ability,
        status=pokemon.status.name if pokemon.status is not None else None,
        moves=[move_to_snapshot(m) for m in pokemon.moves.values()],
        current_hp_fraction=pokemon.current_hp_fraction,
        boosts=pokemon.boosts,
        active=pokemon.active,
        fainted=pokemon.fainted,
        revealed=pokemon.revealed
    )

def field_to_snapshot(battle: Battle) -> FieldSnapshot:
    return FieldSnapshot(
        weather=_snapshot_to_dict(battle.weather),
        fields=_snapshot_to_dict(battle.fields) if battle.fields else None,
        our_hazards=_snapshot_to_dict(battle.side_conditions),
        opponent_hazards=_snapshot_to_dict(battle.opponent_side_conditions),
    )
    
def battle_to_snapshot(battle: Battle) -> BattleSnapshot:
    return BattleSnapshot(
        battle_tag=battle.battle_tag,
        battle_format=battle.format if battle.format is not None else None,
        turn=battle.turn,

        our_active_pokemon=pokemon_to_snapshot(battle.active_pokemon) if battle.active_pokemon else None,
        our_team=[pokemon_to_snapshot(p) for p in battle.team.values()],
        
        opponent_active_pokemon=pokemon_to_snapshot(battle.opponent_active_pokemon) if battle.opponent_active_pokemon else None,
        opponent_team=[pokemon_to_snapshot(p) for p in battle.opponent_team.values()],
        
        field=field_to_snapshot(battle),
        finished=battle.finished,
        won=battle.won,
    )
    
def battle_to_action_option(battle: Battle,) -> list[ActionOption]:
    actions: list[ActionOption] = []
    
    for index, move in enumerate(battle.available_moves):
        actions.append(
            ActionOption(
                id=f"move:{index}:{move.id}",
                type="move",
                move=move_to_snapshot(move),
                switch=None
            )
        )
    
    for index, pokemon in enumerate(battle.available_switches):
        actions.append(
            ActionOption(
                id=f"switch:{index}:{pokemon.species}",
                type="switch",
                move=None,
                switch=pokemon_to_snapshot(pokemon)
            )
        )
    return actions

def battle_to_decision_snapshot(battle: Battle) -> DecisionSnapshot:
    return DecisionSnapshot(
        state=battle_to_snapshot(battle),
        legal_actions=battle_to_action_option(battle),
        forced_switch=battle.force_switch
    )
    