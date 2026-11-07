import asyncio
from showdown_state_tracer.policies.jev_policy import JevSelectionPolicy
from showdown_state_tracer.settings import LOCAL_SERVER
from showdown_state_tracer.tracing_player import TracingRandomPlayer
from poke_env.player import RandomPlayer
from showdown_state_tracer.telemetry import Telemetry
from showdown_state_tracer.randbats_data import RandbatsDataProvider
from pathlib import Path
from typing import Literal


MATCH_MODE: Literal["jev_vs_random", "jev_vs_jev"] = "jev_vs_random"
N_BATTLES = 1
LOG_DIR = Path(__file__).resolve().parent / "logs"


# Parameters: none; configuration comes from the constants above and environment.
# Purpose: run the configured matchup with cached randbats annotations.
# Returns: None after closing player and HTTP clients.
# Pipeline: warms set data, creates the configured opponent, and runs the battles.
async def main() -> None:
    if MATCH_MODE not in {"jev_vs_random", "jev_vs_jev"}:
        raise ValueError(f"Unknown MATCH_MODE: {MATCH_MODE}")
    if N_BATTLES < 1:
        raise ValueError("N_BATTLES must be at least 1")

    policy = JevSelectionPolicy()
    randbats_provider = RandbatsDataProvider()
    players = []
    player_options = {
        "battle_format": "gen9randombattle",
        "max_concurrent_battles": 1,
        "server_configuration": LOCAL_SERVER,
    }

    try:
        await randbats_provider.get_format("gen9randombattle")
        tracing_player = TracingRandomPlayer(
            selection_policy=policy,
            randbats_provider=randbats_provider,
            trace_writer=Telemetry(path=LOG_DIR / "decisions.jsonl"),
            **player_options,
        )
        players.append(tracing_player)
        if MATCH_MODE == "jev_vs_jev":
            opponent = TracingRandomPlayer(
                selection_policy=policy,
                randbats_provider=randbats_provider,
                trace_writer=Telemetry(path=LOG_DIR / "opponent_decisions.jsonl"),
                **player_options,
            )
        else:
            opponent = RandomPlayer(**player_options)
        players.append(opponent)

        print(f"Match mode: {MATCH_MODE} | Battles: {N_BATTLES}")
        await opponent.battle_against(tracing_player, n_battles=N_BATTLES)
    finally:
        await asyncio.gather(
            policy.close(),
            randbats_provider.close(),
            *(player.ps_client.stop_listening() for player in players),
        )


if __name__ == "__main__":
    asyncio.run(main())
