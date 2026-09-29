from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import httpx
import pytest

from app import logging_config
from app.logging_config import scrub_event
from app.main import app
from app.pii import hash_user_id

REQUEST_ID = re.compile(r"req-[0-9a-f]{8}")


@pytest.fixture
def log_path(monkeypatch, tmp_path: Path) -> Path:
    path = tmp_path / "logs.jsonl"
    monkeypatch.setattr(logging_config, "LOG_PATH", path)
    return path


def post_chat(message: str = "Explain observability", headers: dict[str, str] | None = None) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/chat",
                headers=headers or {},
                json={
                    "user_id": "student-01",
                    "session_id": "session-01",
                    "feature": "qa",
                    "message": message,
                },
            )

    return asyncio.run(send())


def api_events(path: Path) -> list[dict]:
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return [event for event in events if event.get("service") == "api"]


def test_generates_request_id_and_timing_headers(log_path: Path) -> None:
    response = post_chat()

    assert REQUEST_ID.fullmatch(response.headers["x-request-id"])
    assert float(response.headers["x-response-time-ms"]) > 0
    assert response.json()["correlation_id"] == response.headers["x-request-id"]


def test_reuses_valid_incoming_request_id(log_path: Path) -> None:
    response = post_chat(headers={"x-request-id": "req-1a2b3c4d"})

    assert response.headers["x-request-id"] == "req-1a2b3c4d"
    assert {event["correlation_id"] for event in api_events(log_path)} == {"req-1a2b3c4d"}


def test_replaces_malformed_incoming_request_id(log_path: Path) -> None:
    response = post_chat(headers={"x-request-id": "student@vinuni.edu.vn"})

    assert REQUEST_ID.fullmatch(response.headers["x-request-id"])
    assert "student@vinuni.edu.vn" not in log_path.read_text(encoding="utf-8")


def test_api_logs_carry_request_context_without_raw_pii(log_path: Path) -> None:
    response = post_chat(message="My email is student@vinuni.edu.vn, phone 0987654321")

    events = api_events(log_path)
    assert [event["event"] for event in events] == ["request_received", "response_sent"]
    for event in events:
        assert event["correlation_id"] == response.headers["x-request-id"]
        assert event["user_id_hash"] == hash_user_id("student-01")
        assert event["session_id"] == "session-01"
        assert event["feature"] == "qa"
        assert event["model"] == "claude-sonnet-4-5"
        assert event["env"]
    raw = log_path.read_text(encoding="utf-8")
    assert "student@vinuni.edu.vn" not in raw
    assert "0987654321" not in raw


def test_scrub_event_covers_nested_values_and_tracebacks() -> None:
    scrubbed = scrub_event(
        None,
        "error",
        {
            "event": "request_failed",
            "session_id": "a@b.co",
            "latency_ms": 12,
            "payload": {"items": ["call 0987654321"]},
            "exception": "ValueError: bad email student@vinuni.edu.vn",
        },
    )

    assert scrubbed == {
        "event": "request_failed",
        "session_id": "[REDACTED_EMAIL]",
        "latency_ms": 12,
        "payload": {"items": ["call [REDACTED_PHONE_VN]"]},
        "exception": "ValueError: bad email [REDACTED_EMAIL]",
    }
