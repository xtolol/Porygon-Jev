"""A revealed opponent narrows complete sampled sets before Jev sees them."""

import asyncio
import json
import logging
from dataclasses import replace
from types import SimpleNamespace

import httpx
from poke_env.battle import Battle, Move, Pokemon

from showdown_state_tracer.models import PokemonSnapshot
from showdown_state_tracer.policies.jev_policy import JevSelectionPolicy
from showdown_state_tracer.randbats_context import annotate_opponent_sets
from showdown_state_tracer.randbats_data import RandbatsDataProvider, RandbatsDataset
from showdown_state_tracer.snapshot import battle_to_decision_snapshot, move_to_snapshot


SETS = {
    "blastoise": {
        "80,whiteherb,torrent,earthquake,hydropump,icebeam,shellsmash,ground": 308,
        "80,whiteherb,torrent,earthquake,hydropump,icebeam,shellsmash,water": 300,
        "80,whiteherb,torrent,hydropump,icebeam,shellsmash,terablast,electric": 326,
        "80,whiteherb,torrent,earthquake,hydropump,icebeam,shellsmash,steel": 257,
        "80,whiteherb,torrent,hydropump,icebeam,shellsmash,terablast,grass": 349,
    }
}


# Parameters: moves are revealed move ids; changes override other observed facts.
# Purpose: build an opponent snapshot with the same semantics as poke-env's state.
# Returns: a Pokémon whose move list contains observed moves only.
# Pipeline: feeds the pure candidate filtering test before the Jev integration test.
def blastoise(*moves, **changes):
    pokemon = PokemonSnapshot(
        types=["WATER"], species="blastoise", level=80, item="unknown_item",
        ability=None, status=None,
        moves=[move_to_snapshot(Move(move, gen=9)) for move in moves],
        current_hp_fraction=1.0, boosts={}, active=True, fainted=False,
        revealed=True,
    )
    return replace(pokemon, **changes)


# Parameters: none; the five fixed entries simulate the published Blastoise sets.
# Purpose: verify conditional frequencies are computed from full-set counts.
# Returns: None; asserts that Shell Smash alone retains both build families.
# Pipeline: protects the move estimate that is attached to Jev's decision state.
def test_revealed_moves_filter_complete_sets():
    data = RandbatsDataset(SETS, "2026-09-30T00:00:00+00:00")
    estimate = annotate_opponent_sets(blastoise("shellsmash"), data)
    moves = {move.move_id: move.sampled_set_fraction for move in estimate.possible_moves}
    assert estimate.matching_set_count == 5
    assert estimate.sampled_set_count == 1540
    assert moves == {"earthquake": 0.5617, "terablast": 0.4383,
                     "hydropump": 1.0, "icebeam": 1.0}

    earthquake = annotate_opponent_sets(blastoise("shellsmash", "earthquake"), data)
    assert earthquake.matching_set_count == 3
    assert earthquake.sampled_set_count == 865
    assert "terablast" not in [m.move_id for m in earthquake.possible_moves]
    tera_blast = annotate_opponent_sets(blastoise("shellsmash", "terablast"), data)
    assert tera_blast.matching_set_count == 2
    assert "earthquake" not in [m.move_id for m in tera_blast.possible_moves]


# Parameters: none; fixture data contains disjoint Tera choices and build moves.
# Purpose: distinguish unknown values from observed attributes and mismatches.
# Returns: None; asserts the source never fabricates certainty for zero matches.
# Pipeline: stops incompatible candidate data from being presented as facts to Jev.
def test_public_attributes_and_missing_matches():
    data = RandbatsDataset(SETS, "2026-09-30T00:00:00+00:00")
    filtered = annotate_opponent_sets(
        blastoise("shellsmash", item="whiteherb", ability="torrent",
                  revealed_tera_type="electric"), data
    )
    assert filtered.matching_set_count == 1
    assert [move.move_id for move in filtered.possible_moves] == [
        "hydropump", "icebeam", "terablast"
    ]
    impossible = annotate_opponent_sets(
        blastoise("earthquake", revealed_tera_type="electric"), data
    )
    assert impossible.status == "no_matching_sets"
    assert impossible.possible_moves == []
    assert annotate_opponent_sets(blastoise(), None).status == "unavailable"


# Parameters: tmp_path provides isolated storage and monkeypatch is unused by HTTP.
# Purpose: verify one download is persisted and reused without another request.
# Returns: None after closing the injected HTTP client.
# Pipeline: tests the pre-battle data fetch and offline local lookup.
def test_provider_downloads_once_and_uses_disk_cache(tmp_path):
    requests = []

    # Parameters: request is the mocked HTTP GET for the complete-set file.
    # Purpose: record requests and return a small published-shape response.
    # Returns: an HTTP 200 response containing the test format data.
    # Pipeline: substitutes the remote static JSON file for this test.
    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, json=SETS)

    # Parameters: none; captured client and cache directory supply dependencies.
    # Purpose: exercise both online download and fresh offline cache reads.
    # Returns: None after assertions and client cleanup.
    # Pipeline: verifies loading behaviour before per-turn annotations run.
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            first = RandbatsDataProvider(cache_dir=tmp_path, client=client)
            assert await first.get_format("gen9randombattle") == await first.get_format("gen9randombattle")
            second = RandbatsDataProvider(cache_dir=tmp_path, client=client)
            assert (await second.get_format("gen9randombattle")).sets_by_species == SETS
            assert await second.get_format("gen9ou") is None
        assert len(requests) == 1
        assert requests[0].endswith("/data/full/gen9randombattle.json")
        assert json.loads((tmp_path / "gen9randombattle.json").read_text())["sets"] == SETS

    asyncio.run(run())


# Parameters: monkeypatch supplies an API key to the existing Jev policy.
# Purpose: prove actual poke-env observations become the Jev state estimate.
# Returns: None; asserts the chosen legal action and outgoing payload.
# Pipeline: covers battle -> snapshot -> candidate annotation -> Jev request.
def test_revealed_move_estimate_reaches_jev(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    battle = Battle("battle-gen9randombattle-estimates", "p1", logging.getLogger("sets"), 9)
    battle._player_role = "p1"
    battle._format = "gen9randombattle"
    ours = Pokemon(gen=9, species="pikachu")
    ours._active = True
    opponent = Pokemon(gen=9, species="blastoise", details="Blastoise, L80")
    opponent._active = True
    opponent._moves["shellsmash"] = Move("shellsmash", gen=9)
    battle._team["p1: Pikachu"] = ours
    battle._opponent_team["p2: Blastoise"] = opponent
    battle._available_moves = [Move("thunderbolt", gen=9)]
    dataset = RandbatsDataset(SETS, "2026-09-30T00:00:00+00:00")
    decision = battle_to_decision_snapshot(battle, randbats_dataset=dataset)
    captured = []
    policy = object.__new__(JevSelectionPolicy)

    # Parameters: payload is the TypeSafe request assembled by JevSelectionPolicy.
    # Purpose: capture its state and provide one valid choice without a network call.
    # Returns: a response object with the normal Jev answer shape.
    # Pipeline: replaces only the external Jev API boundary in the integration test.
    async def fake_send(payload):
        captured.append(payload)
        return SimpleNamespace(json=lambda: {"answers": {"action": {
            "choice": "option_0", "probabilities": {"option_0": 1.0},
            "confidence": 0.8,
        }}})

    policy._send_until_success = fake_send
    selected = asyncio.run(policy.select(decision))
    assert selected.action_id == decision.legal_actions[0].id
    estimate = captured[0]["state"]["opponent_set_estimate"]
    assert estimate["status"] == "available"
    assert estimate["observed_move_ids"] == ["shellsmash"]
    assert {m["move_id"]: m["sampled_set_fraction"] for m in estimate["possible_moves"]} == {
        "earthquake": 0.5617, "terablast": 0.4383,
        "hydropump": 1.0, "icebeam": 1.0,
    }
    assert [m["id"] for m in captured[0]["state"]["opponent_active_pokemon"]["moves"]] == ["shellsmash"]
    assert "opponent_set_estimate" not in json.loads(captured[0]["questions"]["action"]["criteria"]["option_0"])
