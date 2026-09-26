import json
import os
from dataclasses import asdict
import asyncio
import time
import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from showdown_state_tracer.models import (
    DecisionSnapshot,
    PolicySelection,
)


class JevSelectionPolicy:
    ENDPOINT = "https://ai-gateway.vercel.sh/v1/evaluate"
    MODEL = "typesafe-ai/jev"

    def __init__(
        self, min_request_interval: float = 10.0, max_retry_wait: float = 120.0
    ) -> None:
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

    @staticmethod
    def _retry_after_seconds(value: str | None) -> float:
        if value is None:
            return 0.0
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
            except (TypeError, ValueError):
                return 0.0
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())

    async def _send_until_success(
    self,
    payload: dict,
) -> httpx.Response:
        attempt = 0
        async with self._request_lock:
            while True:
                wait = self._next_request_time - time.monotonic()
                if wait > 0:
                    await asyncio.sleep(wait)

                # Set the next start time for every attempt, including retries.
                self._next_request_time = time.monotonic() + self._min_request_interval
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

                server_delay = self._retry_after_seconds(
                    response.headers.get("Retry-After")
                    if response is not None
                    else None
                )
                base_delay = (
                    15.0
                    if response is not None and response.status_code == 429
                    else 2.0
                )
                backoff = min(
                    base_delay * 2 ** min(attempt - 1, 7), self._max_retry_wait
                )
                delay = max(server_delay, backoff) + random.uniform(0.0, 1.0)
                self._next_request_time = max(
                    self._next_request_time, time.monotonic() + delay
                )

                status = (
                    response.status_code
                    if response is not None
                    else "network error"
                )

                print(
                    f"Jev attempt {attempt} returned {status}; "
                    f"next attempt in at least "
                    f"{self._next_request_time - time.monotonic():.1f}s"
                )

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
            "state": {
                **asdict(decision.state),
                "recent_actions": [asdict(action) for action in decision.recent_actions],
            },
            "questions": {
                "action": {
                    "type": "choice",
                    "instructions": (
                        "Choose the legal action that best improves the player's chance"
                        " of winning. For damaging moves, consider the supplied type-effectiveness"
                        " multiplier and whether the move receives STAB. Do not assume that base"
                        " power alone determines the best action. Consider recent_actions"
                        " for repeated lack of observed progress against the same target."
                        " Unchanged HP does not prove immunity: the move may have missed,"
                        " been blocked, or been offset by healing. For utility moves,"
                        " consider self_boosts, heal_fraction and inflicted_status."
                        " The raw boosts field follows the move target and can apply"
                        " to the user or the opponent."
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
