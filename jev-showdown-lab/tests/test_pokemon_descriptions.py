"""Ability and item resources provide independent, cached, offline lookups."""

import json
import warnings

import pytest

from showdown_state_tracer import pokemon_descriptions
from showdown_state_tracer.pokemon_descriptions import (
    get_ability_short_description,
    get_item_short_description,
)


SOUNDPROOF = "This Pokemon is immune to sound-based moves, unless it used the move."
LEFTOVERS = "At the end of every turn, holder restores 1/16 of its max HP."


@pytest.fixture(autouse=True)
def clear_description_cache():
    pokemon_descriptions._load_descriptions.cache_clear()
    yield
    pokemon_descriptions._load_descriptions.cache_clear()


@pytest.mark.parametrize(("identifier", "expected"), [
    ("soundproof", SOUNDPROOF),
    ("levitate", "This Pokemon is immune to Ground; Gravity/Ingrain/Smack Down/Iron Ball nullify it."),
    ("regenerator", "This Pokemon restores 1/3 of its maximum HP, rounded down, when it switches out."),
    ("intimidate", "On switch-in, this Pokemon lowers the Attack of opponents by 1 stage."),
])
def test_bundled_ability_descriptions(identifier, expected):
    assert get_ability_short_description(identifier, 9) == expected


@pytest.mark.parametrize(("identifier", "expected"), [
    ("leftovers", LEFTOVERS),
    ("heavydutyboots", "When switching in, the holder is unaffected by hazards on its side of the field."),
    ("choicescarf", "Holder's Speed is 1.5×, but it can only select the first move it executes."),
    ("lifeorb", "Holder's attacks do 1.3× damage, and it loses 1/10 its max HP after the attack."),
])
def test_bundled_item_descriptions(identifier, expected):
    assert get_item_short_description(identifier, 9) == expected


def test_ids_are_normalized_for_lookup():
    assert get_ability_short_description("Sound Proof", 9) == SOUNDPROOF
    assert get_item_short_description("LEFTOVERS", 9) == LEFTOVERS
    assert get_item_short_description("Heavy-Duty Boots", 9) == (
        get_item_short_description("heavydutyboots", 9)
    )


@pytest.mark.parametrize("identifier", [None, "", "   ", "???", "notarealid"])
def test_unknown_or_empty_ids_are_unavailable(identifier):
    assert get_ability_short_description(identifier, 9) is None
    assert get_item_short_description(identifier, 9) is None


def test_unknown_items_and_unsupported_generations_do_not_load_resources(monkeypatch):
    def unexpected_load(kind):
        pytest.fail("Unknown-item markers and unsupported generations need no resource")

    monkeypatch.setattr(pokemon_descriptions, "_load_descriptions", unexpected_load)
    for marker in ("unknown_item", "unknownitem", "Unknown Item"):
        assert get_item_short_description(marker, 9) is None
    for generation in (8, 10):
        assert get_ability_short_description("soundproof", generation) is None
        assert get_item_short_description("leftovers", generation) is None


def write_resource(tmp_path, kind):
    filename = pokemon_descriptions.RESOURCE_NAMES[kind]
    entries = {"abilities": {"soundproof": SOUNDPROOF}, "items": {"leftovers": LEFTOVERS}}
    data = {
        "schema_version": 1, "generation": 9, "language": "en",
        "source": "https://github.com/smogon/pokemon-showdown",
        "showdown_revision": "a" * 40, kind: entries[kind],
    }
    resource = tmp_path / "data" / filename
    resource.parent.mkdir(exist_ok=True)
    resource.write_text(json.dumps(data), encoding="utf-8")
    return resource


def test_each_resource_is_loaded_once_and_cached_independently(tmp_path, monkeypatch):
    abilities = write_resource(tmp_path, "abilities")
    items = write_resource(tmp_path, "items")
    reads = []

    def fake_files(package):
        reads.append(package)
        return tmp_path

    monkeypatch.setattr(pokemon_descriptions, "files", fake_files)
    assert get_ability_short_description("soundproof", 9) == SOUNDPROOF
    abilities.unlink()
    assert get_item_short_description("leftovers", 9) == LEFTOVERS
    items.unlink()
    assert get_ability_short_description("soundproof", 9) == SOUNDPROOF
    assert get_item_short_description("leftovers", 9) == LEFTOVERS
    assert reads == ["showdown_state_tracer", "showdown_state_tracer"]


@pytest.mark.parametrize("kind", ["abilities", "items"])
@pytest.mark.parametrize("failure", ["missing", "invalid_json", "wrong_metadata", "invalid_text"])
def test_unavailable_resource_warns_once_without_disabling_other_kind(
    tmp_path, monkeypatch, kind, failure,
):
    resources = {name: write_resource(tmp_path, name) for name in ("abilities", "items")}
    resource = resources[kind]
    if failure == "missing":
        resource.unlink()
    elif failure == "invalid_json":
        resource.write_text("not JSON", encoding="utf-8")
    else:
        data = json.loads(resource.read_text(encoding="utf-8"))
        if failure == "wrong_metadata":
            data["generation"] = 8
        else:
            data[kind] = {"invalid": None}
        resource.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(pokemon_descriptions, "files", lambda package: tmp_path)
    lookups = {
        "abilities": (get_ability_short_description, "soundproof", SOUNDPROOF),
        "items": (get_item_short_description, "leftovers", LEFTOVERS),
    }
    failed_lookup, identifier, _ = lookups[kind]
    healthy_lookup, healthy_id, expected = lookups["items" if kind == "abilities" else "abilities"]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert failed_lookup(identifier, 9) is None
        assert healthy_lookup(healthy_id, 9) == expected
        assert failed_lookup(identifier, 9) is None
    assert len(caught) == 1
    assert issubclass(caught[0].category, RuntimeWarning)
    assert f"{kind} descriptions unavailable" in str(caught[0].message)
