"""Type and entry context for one legal switch, without predicting damage."""

from poke_env.battle import PokemonType
from poke_env.data import GenData

from showdown_state_tracer.models import (
    ActionMemorySnapshot,
    BattleSnapshot,
    EntryHazard,
    PokemonSnapshot,
    SwitchContext,
    SwitchMatchup,
)


ENTRY_HAZARDS = ("STEALTH_ROCK", "SPIKES", "TOXIC_SPIKES", "STICKY_WEB")
GROUND_HAZARDS = frozenset(ENTRY_HAZARDS[1:])


def _multiplier(move_type: str | None, target_types: list[str], gen: int) -> float | None:
    if not move_type or not target_types:
        return None
    try:
        attack = PokemonType[move_type]
        defense = [PokemonType[name] for name in target_types]
    except KeyError:
        return None
    if len(defense) > 2:
        return None
    return attack.damage_multiplier(
        defense[0],
        defense[1] if len(defense) == 2 else None,
        type_chart=GenData.from_gen(gen).type_chart,
    )


def _label(multiplier: float) -> str:
    if multiplier == 0:
        return "immune by type"
    if multiplier < 1:
        return "resisted by type"
    if multiplier == 1:
        return "neutral by type"
    return "super effective by type"


def _matchup(source: str, attack_type: str | None, defender: PokemonSnapshot, gen: int
             ) -> SwitchMatchup | None:
    multiplier = _multiplier(attack_type, defender.types, gen)
    if multiplier is None:
        return None
    return SwitchMatchup(source=source, multiplier=multiplier, label=_label(multiplier))


def _entry_hazards(candidate: PokemonSnapshot, state: BattleSnapshot, gen: int
                   ) -> list[EntryHazard]:
    hazards = []
    item = (candidate.item or "").lower().replace("-", "").replace(" ", "")
    ability = (candidate.ability or "").lower().replace(" ", "")
    airborne = (
        "FLYING" in candidate.types or ability == "levitate"
        or item == "airballoon"
    )
    for name in ENTRY_HAZARDS:
        layers = state.field.our_hazards.get(name, 0)
        if not layers:
            continue
        if item == "heavydutyboots":
            exposure = "blocked_by_boots"
            reason = "Known Heavy-Duty Boots prevent entry hazard effects"
        elif name in GROUND_HAZARDS and airborne:
            exposure = "uncertain"
            reason = "Appears airborne; grounding effects are not evaluated"
        elif name in {"STEALTH_ROCK", "SPIKES"} and ability == "magicguard":
            exposure = "uncertain"
            reason = "Known Magic Guard may prevent hazard damage; suppression is not evaluated"
        else:
            exposure = "present"
            reason = "Entry hazard is on our side; its full effect is not calculated"
        if name == "STEALTH_ROCK" and exposure == "present":
            rock = _multiplier("ROCK", candidate.types, gen)
            if rock is not None:
                reason += f"; Rock type effectiveness is {rock}x"
        hazards.append(EntryHazard(name, layers, exposure, reason))
    return hazards


def annotate_switch(
    state: BattleSnapshot,
    candidate: PokemonSnapshot,
    recent_actions: list[ActionMemorySnapshot],
    forced_switch: bool,
    gen: int,
) -> SwitchContext:
    """Derive only visible, per-candidate facts; do not mutate the battle state."""
    opponent = state.opponent_active_pokemon
    revealed = []
    possible_stab = []
    offense = []

    if opponent is not None:
        for move in opponent.moves:
            if move.category == "STATUS" or not move.base_power or move.base_power <= 0:
                continue
            matchup = _matchup(move.id, move.type, candidate, gen)
            if matchup is not None:
                revealed.append(matchup)
        for type_name in opponent.types:
            matchup = _matchup(type_name, type_name, candidate, gen)
            if matchup is not None:
                possible_stab.append(matchup)
        for move in candidate.moves:
            if move.category == "STATUS" or not move.base_power or move.base_power <= 0:
                continue
            matchup = _matchup(move.id, move.type, opponent, gen)
            if matchup is not None:
                offense.append(matchup)

    active = state.our_active_pokemon
    return SwitchContext(
        revealed_move_matchups=revealed,
        possible_stab_matchups=possible_stab,
        offensive_move_matchups=offense,
        entry_hazards=_entry_hazards(candidate, state, gen),
        active_boosts_lost={
            stat: stage for stat, stage in (active.boosts if active else {}).items()
            if stage
        },
        forced_switch=forced_switch,
        last_action_was_switch=(
            recent_actions[-1].action_id.startswith("switch:")
            if recent_actions else None
        ),
        assumptions=[
            "Revealed move matchups use only moves observed on the active opponent",
            "Possible STAB matchups describe types, not known moves or predicted actions",
            "Matchups use typing only; abilities, items, Tera changes, and move effects may alter outcomes",
            "A voluntary switch gives the opponent an action; no opponent action is predicted",
        ],
    )
