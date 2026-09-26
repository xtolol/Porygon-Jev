import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from types import SimpleNamespace

import httpx
import pytest

import showdown_state_tracer.policies.jev_policy as policy_module
from showdown_state_tracer.policies.jev_policy import JevSelectionPolicy


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds


def paced_policy(monkeypatch, responses):
    clock = Clock()
    attempts = []

    class Client:
        async def post(self, url, json):
            attempts.append(clock.now)
            return responses.pop(0)

    monkeypatch.setattr(policy_module, "time", SimpleNamespace(monotonic=clock.monotonic))
    monkeypatch.setattr(policy_module, "asyncio", SimpleNamespace(sleep=clock.sleep))
    monkeypatch.setattr(policy_module.random, "uniform", lambda start, end: 0.0)
    policy = object.__new__(JevSelectionPolicy)
    policy._client = Client()
    policy._request_lock = asyncio.Lock()
    policy._next_request_time = 0.0
    policy._min_request_interval = 10.0
    policy._max_retry_wait = 120.0
    return policy, attempts


def response(status, headers=None):
    return httpx.Response(
        status, headers=headers, request=httpx.Request("POST", JevSelectionPolicy.ENDPOINT)
    )


def test_successive_move_requests_have_minimum_spacing(monkeypatch):
    policy, attempts = paced_policy(monkeypatch, [response(200), response(200)])

    async def run():
        await policy._send_until_success({})
        await policy._send_until_success({})

    asyncio.run(run())
    assert attempts == [0.0, 10.0]


def test_retry_after_controls_retry_and_next_move(monkeypatch):
    policy, attempts = paced_policy(
        monkeypatch, [response(429, {"Retry-After": "45"}), response(200), response(200)]
    )

    async def run():
        await policy._send_until_success({})
        await policy._send_until_success({})

    asyncio.run(run())
    assert attempts == [0.0, 45.0, 55.0]


def test_repeated_429s_back_off_even_without_header(monkeypatch):
    policy, attempts = paced_policy(
        monkeypatch, [response(429), response(429), response(200)]
    )
    asyncio.run(policy._send_until_success({}))
    assert attempts == [0.0, 15.0, 45.0]


def test_retry_after_http_date_is_supported():
    future = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=30))
    assert JevSelectionPolicy._retry_after_seconds(future) == pytest.approx(30, abs=2)
