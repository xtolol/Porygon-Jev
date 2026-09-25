import json
import os
from dataclasses import asdict
import asyncio
import time
import random

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

    async def _send_until_success(
    self,
    payload: dict,
) -> httpx.Response:
        attempt = 0
        async with self._request_lock:
            while True:
                attempt += 1

                try:
                    response = await self._client.post(
                        self.ENDPOINT,
                        json=payload,
                    )

                except httpx.TransportError as error:
                    response = None
                    print(
                        f"Jev transport failure on attempt "
                        f"{attempt}: {error}"
                    )

                if response is not None and response.is_success:
                    print(f"Jev succeeded on attempt {attempt}")
                    return response

                if (
                    response is not None
                    and response.status_code
                    not in {429, 502, 503, 504}
                ):
                    response.raise_for_status()

                retry_after = (
                    response.headers.get("Retry-After")
                    if response is not None
                    else None
                )

                try:
                    server_delay = float(retry_after)
                except (TypeError, ValueError):
                    server_delay = 0.0

                backoff = min(
                    2 ** min(attempt - 1, 6),
                    60.0,
                )

                delay = max(
                    server_delay,
                    backoff,
                    self._min_request_interval,
                )

                delay += random.uniform(0.0, 1.0)

                status = (
                    response.status_code
                    if response is not None
                    else "network error"
                )

                print(
                    f"Jev attempt {attempt} returned {status}; "
                    f"waiting {delay:.1f}s"
                )

                await asyncio.sleep(delay)

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

        response = await self._send_until_success(payload)

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