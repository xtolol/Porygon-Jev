from poke_env.battle import Battle
from poke_env.player import RandomPlayer
from collections import defaultdict

from showdown_state_tracer.battle_memory import BattleMemory
from showdown_state_tracer.models import ActionOption, DecisionRecord

import random

from showdown_state_tracer.snapshot import (
    battle_to_decision_snapshot,
)

from showdown_state_tracer.telemetry import (
    Telemetry,
)

class TracingRandomPlayer(RandomPlayer):
    def __init__(self, trace_writer: Telemetry, selection_policy, seed: int | None = None, **player_options,) -> None:
        super().__init__(**player_options)
        self.trace_writer = trace_writer
        self.random = random.Random(seed)
        self.selection_policy = selection_policy
        self._decision_counts: dict[str, int] = defaultdict(int)
        self._memory = BattleMemory()
        
    async def choose_move(self, battle: Battle) -> int:
        battle_id = battle.battle_tag
        self._memory.resolve(battle)
        decision = battle_to_decision_snapshot(
            battle, recent_actions=self._memory.recent_actions(battle_id)
        )

        self._decision_counts[battle_id] += 1
        decision_number = self._decision_counts[battle_id]
        
        actions_by_id = {action.id: action for action in decision.legal_actions}
        if not decision.legal_actions:
            raise ValueError("No legal actions available for the current battle state.")
        
        try:
            jev_selection = await self.selection_policy.select(
                decision
            )
            
            selected = actions_by_id[jev_selection.action_id]
            print(
            "Jev selected:",
            jev_selection.action_id,
            "confidence:",
            jev_selection.confidence,
            )
            selection_source = "jev"
        except Exception as error:
            print("Jev selection failed:", error)
            jev_selection = None
            selected = self.random.choice(
            decision.legal_actions
        )
            selection_source = "random_fallback"

        order = self._action_to_order(selected, battle)
        self._memory.remember(battle, selected)

        probabilities = jev_selection.probabilities if jev_selection else {}

        selected_probability = probabilities.get(
            selected.id
        )

        ranked_probabilities = sorted(
            probabilities.values(),
            reverse=True,
        )

        probability_margin = (
            ranked_probabilities[0] - ranked_probabilities[1]
            if len(ranked_probabilities) >= 2
            else (1.0 if ranked_probabilities else None)
        )

        record = DecisionRecord(
        battle_id=battle.battle_tag,
        turn=battle.turn,
        decision_number=decision_number,
        decision=decision,
        selected_action_id=selected.id,
        jev_selected_action_id=(
            jev_selection.action_id
            if jev_selection
            else None
        ),
        selection_source=selection_source,
        jev_model=(
            jev_selection.model
            if jev_selection
            else None
        ),
        jev_confidence=(
            jev_selection.confidence
            if jev_selection
            else None
        ),
        jev_probabilities=(
            jev_selection.probabilities
            if jev_selection
            else None
        ),
        selected_probability=selected_probability,
        probability_margin=probability_margin,
        )
        
        self.trace_writer.write(record)
        
        return order

    def _battle_finished_callback(self, battle: Battle) -> None:
        self._memory.clear(battle.battle_tag)
        self._decision_counts.pop(battle.battle_tag, None)
        super()._battle_finished_callback(battle)
    
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
