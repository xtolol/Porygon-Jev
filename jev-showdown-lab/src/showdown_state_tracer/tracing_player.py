from poke_env.battle import Battle
from poke_env.player import RandomPlayer
from poke_env.data import to_id_str
from collections import defaultdict

from showdown_state_tracer.battle_memory import BattleMemory
from showdown_state_tracer.randbats_data import RandbatsDataProvider
from showdown_state_tracer.models import ActionOption, DecisionRecord

import random

from showdown_state_tracer.snapshot import (
    battle_to_decision_snapshot,
)

from showdown_state_tracer.telemetry import (
    Telemetry,
)

class TracingRandomPlayer(RandomPlayer):
    # Parameters: trace_writer stores decisions; selection_policy chooses orders;
    # seed controls fallback; randbats_provider supplies cached set data;
    # player_options are forwarded to poke-env's RandomPlayer.
    # Purpose: configure an agent that annotates each observed battle choice.
    # Returns: a playable instance with battle memory and a shared data provider.
    # Pipeline: constructed once, then choose_move processes each battle request.
    def __init__(
        self, trace_writer: Telemetry, selection_policy, seed: int | None = None,
        randbats_provider: RandbatsDataProvider | None = None, **player_options,
    ) -> None:
        super().__init__(**player_options)
        self.trace_writer = trace_writer
        self.random = random.Random(seed)
        self.selection_policy = selection_policy
        self._decision_counts: dict[str, int] = defaultdict(int)
        self._memory = BattleMemory()
        self.randbats_provider = randbats_provider or RandbatsDataProvider()

    async def _handle_battle_message(self, split_messages):
        # poke-env processes a request (and calls choose_move) inside this batch.
        # Read preceding protocol actions first so the next choice can see them.
        self._observe_battle_messages(split_messages)
        await super()._handle_battle_message(split_messages)

    def _observe_battle_messages(self, split_messages) -> None:
        if not split_messages or not split_messages[0] or not split_messages[0][0].startswith(">battle-"):
            return
        tag = split_messages[0][0][1:]
        battle = self._battles.get(tag)
        if battle is None or battle.player_role not in {"p1", "p2"}:
            return
        opponent_role = "p2" if battle.player_role == "p1" else "p1"
        turn = battle.turn
        active = battle.opponent_active_pokemon
        active_species = active.species if active else None
        species_by_ident = {
            key: pokemon.species for key, pokemon in battle.opponent_team.items()
        }
        for message in split_messages[1:]:
            if len(message) < 3:
                continue
            event = message[1]
            if event in {"request", "win", "tie"}:
                break
            if event == "turn":
                try:
                    turn = int(message[2])
                except ValueError:
                    pass
                continue
            ident = message[2]
            if ident[:2] != opponent_role or event not in {"move", "switch", "drag"}:
                continue
            key = opponent_role + ident[3:] if len(ident) > 3 else ident
            if event in {"switch", "drag"} and len(message) >= 4:
                destination = to_id_str(message[3].split(",", 1)[0])
                self._memory.observe_opponent_event(
                    tag, turn, active_species, "switch",
                    switch_to_species=destination,
                )
                species_by_ident[key] = destination
                active_species = destination
            elif event == "move" and len(message) >= 4:
                actor = species_by_ident.get(key, active_species)
                self._memory.observe_opponent_event(
                    tag, turn, actor, "move", move_id=message[3],
                )
        
    # Parameters: battle is poke-env's current legal decision and public state.
    # Purpose: resolve observations, annotate the opponent, and select an action.
    # Returns: a poke-env order for the validated legal move or switch.
    # Pipeline: loads format data once, sends the decision to Jev, and logs it.
    async def choose_move(self, battle: Battle) -> int:
        battle_id = battle.battle_tag
        self._memory.resolve(battle)
        provider = getattr(self, "randbats_provider", None)
        dataset = await provider.get_format(battle.format) if provider else None
        dataset_args = {"randbats_dataset": dataset} if provider else {}
        decision = battle_to_decision_snapshot(
            battle, recent_actions=self._memory.recent_actions(battle_id),
            recent_opponent_actions=self._memory.recent_opponent_actions(battle_id),
            **dataset_args,
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
