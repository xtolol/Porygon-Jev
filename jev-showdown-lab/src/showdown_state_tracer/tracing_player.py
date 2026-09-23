from poke_env.battle import Battle
from poke_env.player import RandomPlayer

from showdown_state_tracer.snapshot import (
    battle_to_decision_snapshot,
)

from showdown_state_tracer.telemetry import (
    Telemetry,
)

class TracingRandomPlayer(RandomPlayer):
    def __init__(self, trace_writer: Telemetry, **player_options,) -> None:
        super().__init__(**player_options)
        self.trace_writer = trace_writer
        
    def choose_move(self, battle: Battle) -> int:
        snapshot = battle_to_decision_snapshot(battle)
        self.trace_writer.write(snapshot)
        
        return super().choose_move(battle)