"""Bundled descriptions are deterministic, optional, and available offline."""

import json
from pathlib import Path
import shutil
import subprocess
import warnings

import pytest

from showdown_state_tracer import move_descriptions
from showdown_state_tracer.move_descriptions import get_move_short_description


EXPORTER = Path(__file__).resolve().parents[1] / "scripts" / "export_dex_descriptions.cjs"


@pytest.fixture(autouse=True)
def clear_description_cache():
    move_descriptions._load_move_descriptions.cache_clear()
    yield
    move_descriptions._load_move_descriptions.cache_clear()


@pytest.mark.parametrize(("move_id", "expected"), [
    ("recover", "Heals the user by 50% of its max HP."),
    ("toxic", "Badly poisons the target. Poison types can't miss."),
    ("uturn", "User switches out after damaging the target."),
    ("protect", "Prevents moves from affecting the user this turn."),
    ("stealthrock", "Hurts foes on switch-in. Factors Rock weakness."),
    ("terablast", "If Terastallized: Phys. if Atk > SpA, type = Tera."),
])
def test_bundled_descriptions(move_id, expected):
    assert get_move_short_description(move_id, 9) == expected


def test_unknown_id_and_missing_description_are_unavailable():
    assert get_move_short_description("notarealmove", 9) is None
    assert get_move_short_description("nihillight", 9) is None


def test_unsupported_generation_does_not_load_gen9_data(monkeypatch):
    def unexpected_load():
        pytest.fail("Unsupported generations must not load Gen 9 descriptions")

    monkeypatch.setattr(move_descriptions, "_load_move_descriptions", unexpected_load)
    assert get_move_short_description("recover", 8) is None
    assert get_move_short_description("recover", 10) is None


def resource_data():
    return {
        "schema_version": 1,
        "generation": 9,
        "language": "en",
        "source": "https://github.com/smogon/pokemon-showdown",
        "showdown_revision": "a" * 40,
        "moves": {"recover": "Heals the user by 50% of its max HP."},
    }


def write_resource(tmp_path, data):
    resource = tmp_path / "data" / "move_descriptions_gen9.json"
    resource.parent.mkdir()
    resource.write_text(json.dumps(data), encoding="utf-8")
    return resource


def test_resource_is_loaded_only_once(tmp_path, monkeypatch):
    resource = write_resource(tmp_path, resource_data())
    loads = []

    def fake_files(package):
        loads.append(package)
        return tmp_path

    monkeypatch.setattr(move_descriptions, "files", fake_files)
    expected = get_move_short_description("recover", 9)
    resource.unlink()
    assert get_move_short_description("recover", 9) == expected
    assert loads == ["showdown_state_tracer"]


@pytest.mark.parametrize("changes", [
    {"schema_version": 2},
    {"schema_version": True},
    {"generation": 8},
    {"language": "fr"},
    {"showdown_revision": "invalid"},
    {"moves": []},
    {"moves": {}},
    {"moves": {"Recover": "description"}},
    {"moves": {"recover": "   "}},
    {"moves": {"recover": None}},
])
def test_invalid_resource_warns_once_and_returns_none(tmp_path, monkeypatch, changes):
    write_resource(tmp_path, {**resource_data(), **changes})
    monkeypatch.setattr(move_descriptions, "files", lambda package: tmp_path)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert get_move_short_description("recover", 9) is None
        assert get_move_short_description("toxic", 9) is None
    assert len(caught) == 1
    assert issubclass(caught[0].category, RuntimeWarning)
    assert "Move descriptions unavailable" in str(caught[0].message)


@pytest.mark.parametrize("contents", [None, "not JSON", "[]", "null", "\ufffd"])
def test_unreadable_resource_is_optional(tmp_path, monkeypatch, contents):
    if contents is not None:
        resource = tmp_path / "data" / "move_descriptions_gen9.json"
        resource.parent.mkdir()
        resource.write_text(contents, encoding="utf-8")
    monkeypatch.setattr(move_descriptions, "files", lambda package: tmp_path)
    with pytest.warns(RuntimeWarning, match="Move descriptions unavailable"):
        assert get_move_short_description("recover", 9) is None


@pytest.fixture
def showdown_checkout(tmp_path):
    if not shutil.which("node") or not shutil.which("git"):
        pytest.skip("Exporter tests require Node and Git")
    checkout = tmp_path / "showdown checkout"
    dex_path = checkout / "dist" / "sim" / "dex.js"
    dex_path.parent.mkdir(parents=True)
    # Deliberately provide text separately and moves out of order, as Dex does.
    dex_path.write_text("""
exports.Dex = {
    mod(generation) {
        if (generation !== 'gen9') throw new Error('Wrong generation');
        return {
            moves: {all: () => [
                {id: 'uturn', exists: true},
                {id: 'missing', exists: true},
                {id: 'recover', exists: true},
            ]},
            abilities: {all: () => [
                {id: 'soundproof', exists: true},
                {id: 'missing', exists: true},
                {id: 'levitate', exists: true},
            ]},
            items: {all: () => [
                {id: 'lifeorb', exists: true},
                {id: 'missing', exists: true},
                {id: 'leftovers', exists: true},
            ]},
            loadTextData(language) {
                if (language !== 'en') throw new Error('Wrong language');
                return {Moves: {
                    recover: {shortDesc: 'Heals the user by 50% of its max HP.'},
                    uturn: {shortDesc: 'User switches out after damaging the target.'},
                    missing: {shortDesc: ''},
                }, Abilities: {
                    soundproof: {shortDesc: 'Immune to sound-based moves.'},
                    levitate: {shortDesc: 'Immune to Ground-type attacks.'},
                    missing: {shortDesc: ''},
                }, Items: {
                    lifeorb: {shortDesc: 'Boosts attacks at the cost of HP.'},
                    leftovers: {shortDesc: 'Restores HP each turn.'},
                    missing: {shortDesc: ''},
                }};
            },
        };
    },
};
""", encoding="utf-8")
    subprocess.run(["git", "init", "--quiet", str(checkout)], check=True, capture_output=True)
    subprocess.run(["git", "add", "dist"], cwd=checkout, check=True, capture_output=True)
    subprocess.run([
        "git", "-c", "user.name=Exporter Test", "-c", "user.email=exporter@example.invalid",
        "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
        "commit", "--quiet", "-m", "Fixture Dex",
    ], cwd=checkout, check=True, capture_output=True)
    return checkout


def export(checkout, output, kind=None):
    return subprocess.run([
        "node", str(EXPORTER), "--showdown-path", str(checkout), "--output", str(output),
        *(["--kind", kind] if kind is not None else []),
    ], capture_output=True, text=True)


@pytest.mark.parametrize("kind", [None, "moves", "abilities", "items"])
def test_export_joins_text_sorts_ids_and_is_deterministic(showdown_checkout, tmp_path, kind):
    output = tmp_path / "descriptions.json"
    first = export(showdown_checkout, output, kind)
    assert first.returncode == 0, first.stderr
    original = output.read_bytes()
    data = json.loads(original)
    assert data["generation"] == 9
    assert data["language"] == "en"
    assert data["schema_version"] == 1
    assert data["source"] == "https://github.com/smogon/pokemon-showdown"
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=showdown_checkout,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert data["showdown_revision"] == revision
    expected = {
        "moves": {
            "recover": resource_data()["moves"]["recover"],
            "uturn": "User switches out after damaging the target.",
        },
        "abilities": {
            "levitate": "Immune to Ground-type attacks.",
            "soundproof": "Immune to sound-based moves.",
        },
        "items": {
            "leftovers": "Restores HP each turn.",
            "lifeorb": "Boosts attacks at the cost of HP.",
        },
    }[kind or "moves"]
    assert data[kind or "moves"] == expected
    assert list(data[kind or "moves"]) == sorted(expected)
    assert "missing" in first.stdout
    second = export(showdown_checkout, output, kind)
    assert second.returncode == 0, second.stderr
    assert output.read_bytes() == original


@pytest.mark.parametrize("failure", ["unbuilt", "broken_dex", "dirty_source"])
@pytest.mark.parametrize("kind", [None, "abilities", "items"])
def test_failed_export_preserves_existing_resource(showdown_checkout, tmp_path, failure, kind):
    output = tmp_path / "descriptions.json"
    output.write_text("existing export", encoding="utf-8")
    dex_path = showdown_checkout / "dist" / "sim" / "dex.js"
    if failure == "unbuilt":
        dex_path.unlink()
    elif failure == "broken_dex":
        dex_path.write_text("throw new Error('Broken Dex');", encoding="utf-8")
    else:
        source = showdown_checkout / "data" / "moves.ts"
        source.parent.mkdir()
        source.write_text("uncommitted data", encoding="utf-8")
    result = export(showdown_checkout, output, kind)
    assert result.returncode != 0
    assert "Dex description export failed" in result.stderr
    if failure == "unbuilt":
        assert "npm run build" in result.stderr
    assert output.read_text(encoding="utf-8") == "existing export"
    assert not list(tmp_path.glob("*.tmp"))


def test_unknown_export_kind_is_rejected_before_replacing_data(showdown_checkout, tmp_path):
    output = tmp_path / "descriptions.json"
    output.write_text("existing export", encoding="utf-8")
    result = export(showdown_checkout, output, "species")
    assert result.returncode != 0
    assert "Unknown kind" in result.stderr
    assert output.read_text(encoding="utf-8") == "existing export"
