"""Exercise both example matchups and resource cleanup without external services."""

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def runner(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "examples" / "jev_battle.py"
    spec = importlib.util.spec_from_file_location("jev_battle_example", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    state = SimpleNamespace(
        module=module, players=[], policies=[], providers=[], battles=[], failure=None,
    )

    class Policy:
        def __init__(self):
            self.closed = False
            state.policies.append(self)

        async def close(self):
            self.closed = True

    class Provider:
        def __init__(self):
            self.closed = False
            self.formats = []
            state.providers.append(self)

        async def get_format(self, format_id):
            self.formats.append(format_id)
            if state.failure == "warmup":
                raise RuntimeError("warmup failed")

        async def close(self):
            self.closed = True

    class Player:
        def __init__(self, **options):
            self.options = options
            self.stopped = False
            self.ps_client = SimpleNamespace(stop_listening=self.stop_listening)
            state.players.append(self)

        async def stop_listening(self):
            self.stopped = True

        async def battle_against(self, opponent, n_battles):
            state.battles.append((self, opponent, n_battles))
            if state.failure == "battle":
                raise RuntimeError("battle failed")

    class TracingPlayer(Player):
        pass

    class RandomPlayer(Player):
        pass

    monkeypatch.setattr(module, "JevSelectionPolicy", Policy)
    monkeypatch.setattr(module, "RandbatsDataProvider", Provider)
    monkeypatch.setattr(module, "TracingRandomPlayer", TracingPlayer)
    monkeypatch.setattr(module, "RandomPlayer", RandomPlayer)
    monkeypatch.setattr(module, "Telemetry", lambda path: SimpleNamespace(path=path))
    return state


@pytest.mark.parametrize("mode", ["jev_vs_random", "jev_vs_jev"])
def test_match_mode_uses_expected_players_shared_policy_and_separate_logs(runner, mode):
    runner.module.MATCH_MODE = mode
    runner.module.N_BATTLES = 3
    asyncio.run(runner.module.main())

    ours, opponent = runner.players
    assert isinstance(ours, runner.module.TracingRandomPlayer)
    expected_opponent = (
        runner.module.RandomPlayer if mode == "jev_vs_random" else runner.module.TracingRandomPlayer
    )
    assert isinstance(opponent, expected_opponent)
    assert runner.battles == [(opponent, ours, 3)]
    assert runner.providers[0].formats == ["gen9randombattle"]
    assert all(player.options["battle_format"] == "gen9randombattle" for player in runner.players)
    expected_logs = Path(__file__).resolve().parents[1] / "examples" / "logs"
    assert ours.options["trace_writer"].path == expected_logs / "decisions.jsonl"
    if mode == "jev_vs_jev":
        assert len(runner.policies) == len(runner.providers) == 1
        assert opponent.options["selection_policy"] is ours.options["selection_policy"]
        assert opponent.options["randbats_provider"] is ours.options["randbats_provider"]
        assert opponent.options["trace_writer"].path == expected_logs / "opponent_decisions.jsonl"
    assert all(player.stopped for player in runner.players)
    assert runner.policies[0].closed and runner.providers[0].closed


@pytest.mark.parametrize("failure", ["warmup", "battle"])
def test_clients_are_closed_on_failure(runner, failure):
    runner.module.MATCH_MODE = "jev_vs_jev"
    runner.failure = failure
    with pytest.raises(RuntimeError, match=f"{failure} failed"):
        asyncio.run(runner.module.main())
    assert all(player.stopped for player in runner.players)
    assert runner.policies[0].closed and runner.providers[0].closed


@pytest.mark.parametrize(("field", "value"), [("MATCH_MODE", "invalid"), ("N_BATTLES", 0)])
def test_invalid_configuration_is_rejected_before_opening_clients(runner, field, value):
    setattr(runner.module, field, value)
    with pytest.raises(ValueError, match=field):
        asyncio.run(runner.module.main())
    assert not runner.policies and not runner.providers and not runner.players
