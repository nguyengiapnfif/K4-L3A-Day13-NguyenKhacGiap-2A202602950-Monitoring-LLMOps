"""Dashboard 6 panel đọc data/logs.jsonl theo contract config/dashboard.yaml.

Chạy: uv run streamlit run scripts/dashboard.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.metrics import percentile

DASHBOARD_CONFIG = REPO_ROOT / "config" / "dashboard.yaml"
SLO_CONFIG = REPO_ROOT / "config" / "slo.yaml"
LOCAL_TZ = timezone(timedelta(hours=7))  # Asia/Ho_Chi_Minh, không có giờ mùa hè

UNIT_LABELS = {
    "ms": "ms",
    "requests_per_minute": "request/phút",
    "percent": "%",
    "usd": "USD",
    "tokens": "tokens",
    "score_0_to_1": "điểm 0–1",
}
OPERATOR_SYMBOLS = {"lte": "≤", "gte": "≥"}


def log_path() -> Path:
    path = Path(os.getenv("LOG_PATH", "data/logs.jsonl"))
    return path if path.is_absolute() else REPO_ROOT / path


def load_events(path: Path) -> pd.DataFrame:
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    events = pd.DataFrame(rows)
    if events.empty:
        return pd.DataFrame(columns=["ts", "event"])
    events["ts"] = pd.to_datetime(events["ts"], utc=True, format="ISO8601")
    return events


def in_window(events: pd.DataFrame, end: datetime, minutes: int) -> pd.DataFrame:
    start = end - timedelta(minutes=minutes)
    return events[(events["ts"] > start) & (events["ts"] <= end)]


def _values(events: pd.DataFrame, event: str, field: str) -> list:
    if events.empty or field not in events:
        return []
    return events.loc[events["event"] == event, field].dropna().tolist()


def summarize(events: pd.DataFrame, window_minutes: int) -> dict[str, dict]:
    """Tính các aggregation của contract trên cửa sổ thời gian đã lọc."""
    received = int((events["event"] == "request_received").sum()) if not events.empty else 0
    failed = int((events["event"] == "request_failed").sum()) if not events.empty else 0
    latency = [int(v) for v in _values(events, "response_sent", "latency_ms")]
    ttft = [int(v) for v in _values(events, "response_sent", "ttft_ms")]
    tool_results = events["tool_success"].dropna().tolist() if "tool_success" in events else []
    error_types = _values(events, "request_failed", "error_type")
    quality = _values(events, "response_sent", "quality_score")

    return {
        "latency": {
            "p50": percentile(latency, 50),
            "p95": percentile(latency, 95),
            "p99": percentile(latency, 99),
            "ttft_p95": percentile(ttft, 95),
        },
        "traffic": {"count": received, "rate_per_minute": received / window_minutes},
        "errors": {
            "error_rate_pct": failed / received * 100 if received else 0.0,
            "count_by_value": pd.Series(error_types, dtype="object").value_counts().to_dict(),
            "tool_success_rate_pct": (
                sum(bool(v) for v in tool_results) / len(tool_results) * 100 if tool_results else None
            ),
        },
        "cost": {"total": float(sum(_values(events, "response_sent", "cost_usd")))},
        "tokens": {
            "tokens_in": int(sum(_values(events, "response_sent", "tokens_in"))),
            "tokens_out": int(sum(_values(events, "response_sent", "tokens_out"))),
        },
        "quality": {"mean": sum(quality) / len(quality) if quality else None},
    }


def threshold_status(panel: dict, summary: dict) -> tuple[float | None, bool | None]:
    """Trả về (giá trị được so với ngưỡng, có đạt ngưỡng không)."""
    threshold = panel["threshold"]
    if threshold["aggregation"] == "sum_by_field":
        value = max(summary[panel["id"]].values())  # mỗi field đều phải trong ngưỡng
    else:
        value = summary[panel["id"]][threshold["aggregation"]]
    if value is None:
        return None, None
    passed = value <= threshold["value"] if threshold["operator"] == "lte" else value >= threshold["value"]
    return value, passed


# ---------- Vẽ ----------


def _local_minutes(frame: pd.DataFrame) -> pd.Series:
    # Chuyển sang giờ Việt Nam dạng naive để Vega-Lite hiển thị đúng giờ bất kể timezone trình duyệt.
    return frame["ts"].dt.tz_convert(LOCAL_TZ).dt.tz_localize(None).dt.floor("min")


def _alt_datetime(value: datetime) -> alt.DateTime:
    local = value.astimezone(LOCAL_TZ)
    return alt.DateTime(
        year=local.year, month=local.month, date=local.day,
        hours=local.hour, minutes=local.minute, seconds=local.second,
    )


def _rule(value: float, label: str, color: str) -> alt.LayerChart:
    data = pd.DataFrame({"y": [value], "label": [label]})
    rule = alt.Chart(data).mark_rule(color=color, strokeDash=[6, 4], size=2).encode(y="y:Q")
    text = alt.Chart(data).mark_text(align="left", dx=4, dy=-7, color=color, fontSize=11).encode(
        y="y:Q", x=alt.value(0), text="label:N"
    )
    return rule + text


def _time_x(start: datetime, end: datetime) -> alt.X:
    return alt.X(
        "minute:T",
        title="Giờ (ICT)",
        scale=alt.Scale(domain=[_alt_datetime(start), _alt_datetime(end)]),
        axis=alt.Axis(format="%H:%M"),
    )


def _threshold_label(panel: dict) -> str:
    threshold = panel["threshold"]
    unit = UNIT_LABELS.get(panel["unit"], panel["unit"])
    return f"ngưỡng {threshold['aggregation']} {OPERATOR_SYMBOLS[threshold['operator']]} {threshold['value']:g} {unit}"


def chart_latency(events, panel, start, end, slo_ms):
    sent = events[events["event"] == "response_sent"].copy()
    rows = []
    if not sent.empty:
        sent["minute"] = _local_minutes(sent)
        for minute, group in sent.groupby("minute"):
            latency = group["latency_ms"].astype(int).tolist()
            ttft = group["ttft_ms"].astype(int).tolist()
            for name, value in (
                ("P50", percentile(latency, 50)),
                ("P95", percentile(latency, 95)),
                ("P99", percentile(latency, 99)),
                ("TTFT P95", percentile(ttft, 95)),
            ):
                rows.append({"minute": minute, "series": name, "value": value})
    data = pd.DataFrame(rows, columns=["minute", "series", "value"])
    lines = alt.Chart(data).mark_line(point=True).encode(
        x=_time_x(start, end),
        y=alt.Y("value:Q", title="ms"),
        color=alt.Color(
            "series:N",
            title=None,
            # Tránh đỏ/cam để không lẫn với đường ngưỡng và đường SLO.
            scale=alt.Scale(
                domain=["P50", "P95", "P99", "TTFT P95"],
                range=["#4c78a8", "#b279a2", "#72b7b2", "#54a24b"],
            ),
        ),
        tooltip=["minute:T", "series:N", "value:Q"],
    )
    return lines + _rule(panel["threshold"]["value"], _threshold_label(panel), "#d62728") + _rule(
        slo_ms, f"SLO latency ≤ {slo_ms:g} ms", "#ff7f0e"
    )


def chart_count_per_minute(events, panel, start, end, event, title):
    frame = events[events["event"] == event].copy()
    if not frame.empty:
        frame["minute"] = _local_minutes(frame)
    data = frame.groupby("minute").size().reset_index(name="value") if not frame.empty else pd.DataFrame(
        columns=["minute", "value"]
    )
    bars = alt.Chart(data).mark_bar(size=8).encode(
        x=_time_x(start, end), y=alt.Y("value:Q", title=title), tooltip=["minute:T", "value:Q"]
    )
    return bars + _rule(panel["threshold"]["value"], _threshold_label(panel), "#d62728")


def chart_error_rate(events, panel, start, end):
    frame = events[events["event"].isin(["request_received", "request_failed"])].copy()
    rows = []
    if not frame.empty:
        frame["minute"] = _local_minutes(frame)
        for minute, group in frame.groupby("minute"):
            received = (group["event"] == "request_received").sum()
            failed = (group["event"] == "request_failed").sum()
            rows.append({"minute": minute, "value": failed / received * 100 if received else 0.0})
    data = pd.DataFrame(rows, columns=["minute", "value"])
    bars = alt.Chart(data).mark_bar(size=8, color="#d62728").encode(
        x=_time_x(start, end), y=alt.Y("value:Q", title="error rate (%)"), tooltip=["minute:T", "value:Q"]
    )
    return bars + _rule(panel["threshold"]["value"], _threshold_label(panel), "#d62728")


def chart_cost(events, panel, start, end):
    sent = events[events["event"] == "response_sent"].copy()
    if sent.empty:
        data = pd.DataFrame(columns=["minute", "per_minute", "cumulative"])
    else:
        sent["minute"] = _local_minutes(sent)
        data = sent.groupby("minute")["cost_usd"].sum().reset_index(name="per_minute")
        data["cumulative"] = data["per_minute"].cumsum()
    base = alt.Chart(data).encode(x=_time_x(start, end))
    bars = base.mark_bar(size=8, opacity=0.6).encode(
        y=alt.Y("per_minute:Q", title="USD"), tooltip=["minute:T", "per_minute:Q", "cumulative:Q"]
    )
    line = base.mark_line(point=True, color="#2ca02c").encode(y="cumulative:Q")
    return bars + line + _rule(panel["threshold"]["value"], _threshold_label(panel), "#d62728")


def chart_tokens(summary, panel):
    data = pd.DataFrame(
        {"field": list(summary["tokens"].keys()), "value": list(summary["tokens"].values())}
    )
    bars = alt.Chart(data).mark_bar().encode(
        x=alt.X("field:N", title=None), y=alt.Y("value:Q", title="tokens"), tooltip=["field:N", "value:Q"]
    )
    return bars + _rule(panel["threshold"]["value"], _threshold_label(panel), "#d62728")


def chart_quality(events, panel, start, end):
    sent = events[events["event"] == "response_sent"].copy()
    if sent.empty:
        data = pd.DataFrame(columns=["minute", "value"])
    else:
        sent["minute"] = _local_minutes(sent)
        data = sent.groupby("minute")["quality_score"].mean().reset_index(name="value")
    line = alt.Chart(data).mark_line(point=True).encode(
        x=_time_x(start, end),
        y=alt.Y("value:Q", title="điểm 0–1", scale=alt.Scale(domain=[0, 1])),
        tooltip=["minute:T", "value:Q"],
    )
    return line + _rule(panel["threshold"]["value"], _threshold_label(panel), "#d62728")


def _fmt(value, pattern: str) -> str:
    return "—" if value is None else pattern.format(value)


def render_panel(panel, events, summary, start, end, slo):
    unit = UNIT_LABELS.get(panel["unit"], panel["unit"])
    value, passed = threshold_status(panel, summary)
    status = "chưa có dữ liệu" if passed is None else ("✅ trong ngưỡng" if passed else "🔴 vượt ngưỡng")
    st.subheader(panel["title"])
    st.caption(f"Đơn vị: {unit} · {_threshold_label(panel)} · hiện tại {_fmt(value, '{:,.4g}')} → {status}")

    data = summary[panel["id"]]
    panel_id = panel["id"]
    if panel_id == "latency":
        cols = st.columns(4)
        for col, key, label in zip(cols, ("p50", "p95", "p99", "ttft_p95"), ("P50", "P95", "P99", "TTFT P95")):
            col.metric(f"{label} (ms)", _fmt(data[key], "{:,.0f}"))
        slo_ms = slo["sli"]["latency_threshold_ms"]
        good = int(((events["event"] == "response_sent") & (events.get("latency_ms", 0) <= slo_ms)).sum()) if not events.empty else 0
        total = summary["traffic"]["count"]
        st.caption(
            f"SLO `{slo['name']}`: {good}/{total} request thành công ≤ {slo_ms} ms "
            f"({_fmt(good / total * 100 if total else None, '{:.1f}')}%), mục tiêu {slo['target_percent']}%"
        )
        chart = chart_latency(events, panel, start, end, slo_ms)
    elif panel_id == "traffic":
        cols = st.columns(2)
        cols[0].metric("Tổng request", f"{data['count']:,}")
        cols[1].metric("Request/phút (TB cửa sổ)", f"{data['rate_per_minute']:.2f}")
        chart = chart_count_per_minute(events, panel, start, end, "request_received", "request/phút")
    elif panel_id == "errors":
        cols = st.columns(3)
        cols[0].metric("Error rate (%)", f"{data['error_rate_pct']:.1f}")
        cols[1].metric("Retrieval success (%)", _fmt(data["tool_success_rate_pct"], "{:.1f}"))
        breakdown = ", ".join(f"{k}: {v}" for k, v in data["count_by_value"].items()) or "không có lỗi"
        cols[2].metric("Lỗi theo loại", breakdown)
        chart = chart_error_rate(events, panel, start, end)
    elif panel_id == "cost":
        cols = st.columns(2)
        cols[0].metric("Tổng cost (USD)", f"{data['total']:.4f}")
        cols[1].metric("Đã dùng ngân sách", f"{data['total'] / panel['threshold']['value'] * 100:.1f}%")
        chart = chart_cost(events, panel, start, end)
    elif panel_id == "tokens":
        cols = st.columns(2)
        cols[0].metric("Input tokens", f"{data['tokens_in']:,}")
        cols[1].metric("Output tokens", f"{data['tokens_out']:,}")
        chart = chart_tokens(summary, panel)
    else:
        st.metric("Quality trung bình", _fmt(data["mean"], "{:.3f}"))
        chart = chart_quality(events, panel, start, end)
    st.altair_chart(chart.properties(height=230), use_container_width=True)


def main() -> None:
    st.set_page_config(page_title="Day 13 Dashboard", layout="wide")
    config = yaml.safe_load(DASHBOARD_CONFIG.read_text(encoding="utf-8"))["dashboard"]
    slo = yaml.safe_load(SLO_CONFIG.read_text(encoding="utf-8"))["primary_slo"]
    minutes = config["time_range_minutes"]

    @st.fragment(run_every=config["refresh_seconds"])
    def render() -> None:
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=minutes)
        events = in_window(load_events(log_path()), end, minutes)
        summary = summarize(events, minutes)

        st.title(config["title"])
        local_start, local_end = start.astimezone(LOCAL_TZ), end.astimezone(LOCAL_TZ)
        st.caption(
            f"Nguồn `data/logs.jsonl` · Time range: {minutes} phút gần nhất "
            f"({local_start:%H:%M}–{local_end:%H:%M} ICT, {local_end:%d/%m/%Y}) · "
            f"Tự refresh mỗi {config['refresh_seconds']} giây · cập nhật lúc {local_end:%H:%M:%S}"
        )
        if events.empty:
            st.warning("Không có log trong cửa sổ thời gian. Chạy API và `python scripts/load_test.py` trước.")

        panels = config["panels"]
        for row in range(0, len(panels), 2):
            for column, panel in zip(st.columns(2), panels[row : row + 2]):
                with column, st.container(border=True):
                    render_panel(panel, events, summary, start, end, slo)

    render()


if __name__ == "__main__":
    main()
