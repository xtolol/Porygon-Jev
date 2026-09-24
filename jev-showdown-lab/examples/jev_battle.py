import asyncio
from showdown_state_tracer.policies.jev_policy import JevSelectionPolicy
from showdown_state_tracer.settings import LOCAL_SERVER
from showdown_state_tracer.tracing_player import TracingRandomPlayer
from poke_env.player import RandomPlayer
from showdown_state_tracer.telemetry import Telemetry
from pathlib import Path


async def main():
    policy = JevSelectionPolicy()

    random_player = RandomPlayer(
        max_concurrent_battles=1,
        server_configuration=LOCAL_SERVER,
    )
    tracing_player = TracingRandomPlayer(
        selection_policy=policy,
        trace_writer=Telemetry(path=Path("logs/decisions.jsonl")),
        max_concurrent_battles=1,
        server_configuration=LOCAL_SERVER,
    )

    try:
        await tracing_player.battle_against(
            random_player,
            n_battles=1,
        )
    finally:
        await policy.close()
        await tracing_player.ps_client.stop_listening()
        await random_player.ps_client.stop_listening()

if __name__ == "__main__":
    asyncio.run(main())