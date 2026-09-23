from poke_env.battle import Battle
from poke_env.player import RandomPlayer

from showdown_state_tracer.models import ActionOption, DecisionRecord

import random

from showdown_state_tracer.snapshot import (
    battle_to_decision_snapshot,
)

from showdown_state_tracer.telemetry import (
    Telemetry,
)

class TracingRandomPlayer(RandomPlayer):
    def __init__(self, trace_writer: Telemetry, seed: int | None = None, **player_options,) -> None:
        super().__init__(**player_options)
        self.trace_writer = trace_writer
        self.random = random.Random(seed)
        
    def choose_move(self, battle: Battle) -> int:
        decision = battle_to_decision_snapshot(battle)
        if not decision.legal_actions:
            raise ValueError("No legal actions available for the current battle state.")
        
        selected = self.random.choice(decision.legal_actions)
        
        order = self._action_to_order(selected, battle)
        
        record = DecisionRecord(
            decision=decision,
            selected_action_id=selected.id,
        )
        
        self.trace_writer.write(record)
        
        return order
    
    def _action_to_order(self, action: ActionOption, battle: Battle):
        _, index_text, _ = action.id.split(":", maxsplit=2)
        index = int(index_text)
        
        if action.type == "move":
            move = battle.available_moves[index]
            return self.create_order(move)
        
        if action.type == "switch":
            pokemon = battle.available_switches[index]
            return self.create_order(pokemon)
        
        raise ValueError(f"Unknown action type: {action.type}")