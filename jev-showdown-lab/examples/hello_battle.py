import asyncio
from poke_env.player import RandomPlayer
from showdown_state_tracer.tracing_player import TracingRandomPlayer
from showdown_state_tracer.settings import LOCAL_SERVER
from showdown_state_tracer.telemetry import Telemetry
from pathlib import Path

async def main():
    player_1 = TracingRandomPlayer(
        trace_writer=Telemetry(path=Path("logs/decisions.jsonl")),
        max_concurrent_battles=1,
        server_configuration=LOCAL_SERVER
    )
    player_2 = RandomPlayer(
        max_concurrent_battles=1, 
        server_configuration=LOCAL_SERVER
    )

    await player_1.battle_against(player_2, n_battles=1)

    print(f"Finished battles: {player_1.n_finished_battles}")
    print(f"Player 1 wins: {player_1.n_won_battles}")

if __name__ == "__main__":
    asyncio.run(main())