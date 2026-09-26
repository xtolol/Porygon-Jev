# Data models for traced battle states

from dataclasses import dataclass, field
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
    boosts: dict[str, int] | None = None  # poke-env primary boosts; recipient follows target
    self_boosts: dict[str, int] | None = None  # boosts to the user, including self-target moves
    heal_fraction: float | None = None  # fraction of max HP restored to the user
    inflicted_status: str | None = None  # primary status effect, if any
    
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

@dataclass(frozen=True)
class MoveEffectiveness:
    receives_stab: bool | None
    effectiveness_multiplier: float | None
    effectiveness_label: str | None

    
@dataclass(frozen=True, slots=True)
class ActionOption:
    # Information about one action option.
    
    id: str
    type: Literal["move", "switch", "default"]
    move: MoveSnapshot | None = None
    switch: PokemonSnapshot | None = None
    move_effectiveness: MoveEffectiveness | None = None


ActionOutcome = Literal[
    "damage_observed",
    "no_net_damage_observed",
    "target_recovered",
    "target_unavailable",
    "switch_selected",
]


@dataclass(frozen=True, slots=True)
class ActionMemorySnapshot:
    turn: int
    action_id: str
    actor_species: str | None
    target_species: str | None
    target_hp_before: float | None
    target_hp_after: float | None
    damage_fraction: float | None
    outcome: ActionOutcome
    known_target_ability: str | None


@dataclass(frozen=True, slots=True)
class DecisionSnapshot:
    # Information about the decision state.
    
    state: BattleSnapshot
    legal_actions: list[ActionOption]
    forced_switch: bool
    recent_actions: list[ActionMemorySnapshot] = field(default_factory=list)
    schema_version: int = 3
    
@dataclass(frozen=True, slots=True)
class DecisionRecord:
    battle_id: str
    decision_number: int
    turn: int

    decision: DecisionSnapshot
    selected_action_id: str
    jev_selected_action_id: str | None
    selection_source: Literal["jev", "random_fallback"]

    jev_model: str | None
    jev_confidence: float | None
    jev_probabilities: dict[str, float] | None

    selected_probability: float | None
    probability_margin: float | None  # difference between top two probabilities

@dataclass(frozen=True)
class PolicySelection:
    action_id: str
    probabilities: dict[str, float]
    confidence: float | None
    model: str
    generation_id: str | None = None
