"""Exercise the direct TypeSafe request and Choice response contract."""

import asyncio
import json
from dataclasses import dataclass

import httpx
import pytest

import showdown_state_tracer.policies.jev_policy as policy_module
from showdown_state_tracer.models import ActionOption, DecisionSnapshot
from showdown_state_tracer.policies.jev_policy import JevSelectionPolicy


@dataclass
class State:
    battle_tag: str = "battle-direct-api"


def test_direct_request_auth_payload_and_choice_response(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-direct-key")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={
            "model": "jev-1.13.0",
            "answers": {"action": {
                "type": "choice",
                "choice": "option_1",
                "probabilities": {"option_0": 0.2, "option_1": 0.8},
                "confidence": 0.7,
            }},
            "usage": {"input_tokens": 200, "output_tokens": 12},
        })

    real_client = httpx.AsyncClient

    def make_client(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(policy_module.httpx, "AsyncClient", make_client)
    decision = DecisionSnapshot(
        state=State(),
        legal_actions=[
            ActionOption(id="move:0:earthquake", type="move"),
            ActionOption(id="switch:0:gastrodon", type="switch"),
        ],
        forced_switch=False,
    )

    async def run():
        policy = JevSelectionPolicy()
        try:
            return await policy.select(decision)
        finally:
            await policy.close()

    selected = asyncio.run(run())
    request = requests[0]
    payload = json.loads(request.content)

    assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
    assert request.headers["Authorization"] == "Bearer test-direct-key"
    assert request.headers["Content-Type"] == "application/json"
    assert payload["model"] == "jev-latest"
    assert payload["questions"]["action"]["type"] == "choice"
    assert list(payload["questions"]["action"]["criteria"]) == ["option_0", "option_1"]
    assert selected.action_id == "switch:0:gastrodon"
    assert selected.probabilities == {"move:0:earthquake": 0.2, "switch:0:gastrodon": 0.8}
    assert selected.model == "jev-1.13.0"
    assert selected.confidence == 0.7
    assert selected.generation_id is None


def test_direct_key_is_required_even_when_old_gateway_key_is_set(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "old-gateway-key")

    with pytest.raises(RuntimeError, match="TYPESAFE_API_KEY"):
        JevSelectionPolicy()
