from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
import yaml

from scripts.dashboard import DASHBOARD_CONFIG, in_window, summarize, threshold_status

NOW = datetime(2026, 9, 29, 9, 0, tzinfo=timezone.utc)


def event(minutes_ago: float, name: str, **fields) -> dict:
    return {"ts": NOW - timedelta(minutes=minutes_ago), "event": name, **fields}


def sample_events() -> pd.DataFrame:
    rows = [event(90, "request_received")]  # nằm ngoài cửa sổ 60 phút
    for i, latency in enumerate([200, 300, 400]):
        rows += [
            event(10 + i, "request_received"),
            event(10 + i, "response_sent", latency_ms=latency, ttft_ms=50, cost_usd=0.002,
                  tokens_in=40, tokens_out=100, quality_score=0.8, tool_success=True),
        ]
    rows += [
        event(5, "request_received"),
        event(5, "request_failed", error_type="RuntimeError", tool_success=False),
    ]
    return pd.DataFrame(rows)


def panels() -> dict[str, dict]:
    config = yaml.safe_load(DASHBOARD_CONFIG.read_text(encoding="utf-8"))["dashboard"]
    return {panel["id"]: panel for panel in config["panels"]}


def test_summary_matches_contract_aggregations() -> None:
    summary = summarize(in_window(sample_events(), NOW, 60), 60)

    assert summary["latency"]["p50"] == 300
    assert summary["latency"]["p95"] == 400
    assert summary["traffic"] == {"count": 4, "rate_per_minute": 4 / 60}
    assert summary["errors"]["error_rate_pct"] == 25
    assert summary["errors"]["count_by_value"] == {"RuntimeError": 1}
    assert summary["errors"]["tool_success_rate_pct"] == 75
    assert summary["cost"]["total"] == pytest.approx(0.006)
    assert summary["tokens"] == {"tokens_in": 120, "tokens_out": 300}
    assert summary["quality"]["mean"] == pytest.approx(0.8)


def test_threshold_status_uses_contract_operator() -> None:
    summary = summarize(in_window(sample_events(), NOW, 60), 60)
    by_id = panels()

    assert threshold_status(by_id["latency"], summary) == (400, True)
    assert threshold_status(by_id["errors"], summary) == (25, False)
    assert threshold_status(by_id["quality"], summary)[1] is True
    assert threshold_status(by_id["tokens"], summary) == (300, True)


def test_empty_window_has_no_status() -> None:
    summary = summarize(pd.DataFrame(columns=["ts", "event"]), 60)

    assert threshold_status(panels()["quality"], summary) == (None, None)
    assert summary["errors"]["error_rate_pct"] == 0.0
