import asyncio
from showdown_state_tracer.policies.jev_policy import JevSelectionPolicy
from showdown_state_tracer.settings import LOCAL_SERVER
from showdown_state_tracer.tracing_player import TracingRandomPlayer
from poke_env.player import RandomPlayer
from showdown_state_tracer.telemetry import Telemetry
from showdown_state_tracer.randbats_data import RandbatsDataProvider
from pathlib import Path


# Parameters: none; configuration comes from the local server and environment.
# Purpose: run a Jev-versus-random battle with cached randbats annotations.
# Returns: None after closing player and HTTP clients.
# Pipeline: warms set data before battle events are sent to the player.
async def main():
    policy = JevSelectionPolicy()
    randbats_provider = RandbatsDataProvider()
    await randbats_provider.get_format("gen9randombattle")

    tracing_player = TracingRandomPlayer(
        selection_policy=policy,
        randbats_provider=randbats_provider,
        trace_writer=Telemetry(path=Path("logs/decisions.jsonl")),
        max_concurrent_battles=1,
        server_configuration=LOCAL_SERVER,
    )
    random_player = RandomPlayer(
        max_concurrent_battles=1,
        server_configuration=LOCAL_SERVER,
    )

    try:
        await random_player.battle_against(
            tracing_player,
            n_battles=1,
        )
    finally:
        await policy.close()
        await randbats_provider.close()
        await tracing_player.ps_client.stop_listening()
        await random_player.ps_client.stop_listening()
if __name__ == "__main__":
    asyncio.run(main())
