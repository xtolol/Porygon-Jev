"""Turn observed opponent facts into compact random-battle set estimates."""

from collections import Counter

from poke_env.data import to_id_str

from showdown_state_tracer.models import (
    OpponentSetEstimate,
    PokemonSnapshot,
    PossibleMoveEstimate,
)
from showdown_state_tracer.randbats_data import RandbatsDataset


SOURCE = "pkmn/randbats full; simulated team frequencies"
MAX_POSSIBLE_MOVES = 8


# Parameters: pokemon holds observed public attributes; dataset has complete sets.
# Purpose: eliminate sets incompatible with revealed moves, level, item, ability or Tera.
# Returns: one estimate of unrevealed moves, or an explicit unavailable/no-match result.
# Pipeline: its output accompanies the opponent snapshot in each Jev decision.
def annotate_opponent_sets(
    pokemon: PokemonSnapshot, dataset: RandbatsDataset | None
) -> OpponentSetEstimate:
    species = to_id_str(pokemon.species)
    observed = {to_id_str(move.id) for move in pokemon.moves}
    base = dict(
        species=pokemon.species,
        observed_move_ids=sorted(observed),
        source=SOURCE,
        data_retrieved_at=dataset.retrieved_at if dataset else None,
    )
    if dataset is None or species not in dataset.sets_by_species:
        return OpponentSetEstimate(
            **base, status="unavailable", possible_moves=[], matching_set_count=0,
            sampled_set_count=0, omitted_move_count=0,
        )

    item = to_id_str(pokemon.item) if pokemon.item else None
    ability = to_id_str(pokemon.ability) if pokemon.ability else None
    tera = to_id_str(pokemon.revealed_tera_type) if pokemon.revealed_tera_type else None
    move_counts: Counter[str] = Counter()
    sampled_set_count = 0
    matching_set_count = 0
    for key, count in dataset.sets_by_species[species].items():
        parts = key.split(",")
        if len(parts) != 8 or not isinstance(count, int) or count <= 0:
            continue
        level, set_item, set_ability, *rest = parts
        moves, set_tera = set(rest[:4]), rest[4]
        if pokemon.level > 0 and str(pokemon.level) != level:
            continue
        if item not in {None, "unknownitem"} and item != set_item:
            continue
        if ability is not None and ability != set_ability:
            continue
        if tera is not None and tera != set_tera:
            continue
        if not observed.issubset(moves):
            continue
        matching_set_count += 1
        sampled_set_count += count
        move_counts.update({move: count for move in moves - observed})

    if sampled_set_count == 0:
        return OpponentSetEstimate(
            **base, status="no_matching_sets", possible_moves=[],
            matching_set_count=0, sampled_set_count=0, omitted_move_count=0,
        )

    ranked = sorted(move_counts.items(), key=lambda entry: (-entry[1], entry[0]))
    return OpponentSetEstimate(
        **base,
        status="available",
        possible_moves=[
            PossibleMoveEstimate(move, round(count / sampled_set_count, 4))
            for move, count in ranked[:MAX_POSSIBLE_MOVES]
        ],
        matching_set_count=matching_set_count,
        sampled_set_count=sampled_set_count,
        omitted_move_count=max(0, len(ranked) - MAX_POSSIBLE_MOVES),
    )
