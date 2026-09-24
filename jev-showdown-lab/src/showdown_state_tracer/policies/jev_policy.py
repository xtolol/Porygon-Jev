import json
import os
from dataclasses import asdict
import asyncio
import time

import httpx

from showdown_state_tracer.models import (
    DecisionSnapshot,
    PolicySelection,
)


class JevSelectionPolicy:
    ENDPOINT = "https://ai-gateway.vercel.sh/v1/evaluate"
    MODEL = "typesafe-ai/jev"

    def __init__(self, min_request_interval: float = 3.0, max_retry_wait: float = 5.0,) -> None:
        api_key = os.getenv("AI_GATEWAY_API_KEY")

        if not api_key:
            raise RuntimeError(
                "AI_GATEWAY_API_KEY environment variable is not set"
            )

        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(10.0, connect=5.0),
        )
        self._min_request_interval = min_request_interval
        self._max_retry_wait = max_retry_wait

        self._request_lock = asyncio.Lock()
        self._next_request_time = 0.0

    async def _send_request(
    self,
    payload: dict,
) -> httpx.Response:
        async with self._request_lock:
            remaining_delay = (
                self._next_request_time - time.monotonic()
            )

            if remaining_delay > 0:
                await asyncio.sleep(remaining_delay)

            response = await self._client.post(
                self.ENDPOINT,
                json=payload,
            )

            self._next_request_time = (
                time.monotonic() + self._min_request_interval
            )

            if response.status_code != 429:
                response.raise_for_status()
                return response

            retry_header = response.headers.get("Retry-After")

            try:
                retry_delay = float(retry_header)
            except (TypeError, ValueError):
                retry_delay = self._min_request_interval

            if retry_delay > self._max_retry_wait:
                response.raise_for_status()

            await asyncio.sleep(retry_delay)

            response = await self._client.post(
                self.ENDPOINT,
                json=payload,
            )

            self._next_request_time = (
                time.monotonic() + self._min_request_interval
            )

            response.raise_for_status()
            return response

    async def select(
        self,
        decision: DecisionSnapshot,
    ) -> PolicySelection:
        legal_actions = decision.legal_actions

        if not legal_actions:
            raise ValueError("Decision contains no legal actions")

        option_lookup = {
            f"option_{index}": action
            for index, action in enumerate(legal_actions)
        }

        criteria = {
            label: json.dumps(
                asdict(action),
                default=str,
                separators=(",", ":"),
            )
            for label, action in option_lookup.items()
        }

        payload = {
            "model": self.MODEL,
            "state": asdict(decision.state),
            "questions": {
                "action": {
                    "type": "choice",
                    "instructions": (
                        "Choose the legal action that best improves the "
                        "player's expected chance of winning."
                    ),
                    "criteria": criteria,
                }
            },
        }

        response = await self._send_request(payload)

        response_data = response.json()
        answer = response_data["answers"]["action"]
        selected_label = answer["choice"]

        if selected_label not in option_lookup:
            raise ValueError(
                f"Jev returned unknown option: {selected_label}"
            )

        selected_action = option_lookup[selected_label]

        probabilities = {
            option_lookup[label].id: probability
            for label, probability in answer["probabilities"].items()
            if label in option_lookup
        }

        gateway_metadata = response_data.get(
            "providerMetadata", {}
        ).get("gateway", {})

        return PolicySelection(
            action_id=selected_action.id,
            probabilities=probabilities,
            confidence=answer.get("confidence"),
            model=response_data.get("model", self.MODEL),
            generation_id=gateway_metadata.get("generationId"),
        )

    

    async def close(self) -> None:
        await self._client.aclose()