# Data models for traced battle states

from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True, slots=True)
class MoveSnapshot:
    # Information about one pokemon move.
    
    id: str
    name: str
    type: str | None
    base_power: int | None
    category: str | None
    accuracy: float | None
    priority: int
    target: str | None
    current_pp: int | None = None
    max_pp: int | None = None
    boosts: dict[str, int] | None = None  # stat boosts, e.g. {"atk": 1, "def": -1}
    
    is_protect_move: bool = False

@dataclass(frozen=True, slots=True)
class PokemonSnapshot:
    # Information about one pokemon.
    types: list[str]
    species: str
    level: int
    item: str | None
    ability: str | None
    status: str | None
    moves: list[MoveSnapshot]
    current_hp_fraction: float  # float between 0 and 1
    boosts: dict[str, int]  # stat boosts, e.g. {"atk": 1, "def": -1}
    active: bool | None
    fainted: bool
    revealed: bool  # whether the opponent has seen this pokemon's species
    
@dataclass(frozen=True, slots=True)
class FieldSnapshot:
    # Information about the battle field.
    weather: dict[str, int] | None  # e.g. {"type": "raindance", "turns_left": 3}
    fields: dict[str, int] | None  # e.g. [{"type": "electricterrain", "turns_left": 3}]
    our_hazards: dict[str, int]  # e.g. {"stealthrock": 1, "spikes": 2}
    opponent_hazards: dict[str, int]  # e.g. {"stealthrock": 1, "spikes": 2}
    
@dataclass(frozen=True, slots=True)
class BattleSnapshot:
    # Information about the battle state.
    battle_tag: str
    battle_format: str | None
    turn: int

    our_active_pokemon: PokemonSnapshot | None
    our_team: list[PokemonSnapshot]
    
    opponent_active_pokemon: PokemonSnapshot | None
    opponent_team: list[PokemonSnapshot]
    
    field: FieldSnapshot
    
    finished: bool
    won: bool | None  # True if we won, False if we lost, None if battle is ongoing
    
    
@dataclass(frozen=True, slots=True)
class ActionOption:
    # Information about one action option.
    
    id: str
    type: Literal["move", "switch", "default"]
    move: MoveSnapshot | None = None
    switch: PokemonSnapshot | None = None
    

@dataclass(frozen=True, slots=True)
class DecisionSnapshot:
    # Information about the decision state.
    
    state: BattleSnapshot
    legal_actions: list[ActionOption]
    forced_switch: bool
    schema_version: int = 1
    
@dataclass(frozen=True, slots=True)
class DecisionRecord:
    decision: DecisionSnapshot
    selected_action_id: str