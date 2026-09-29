from __future__ import annotations

import json

import pytest
from langfuse import Langfuse
from langfuse._client.resource_manager import LangfuseResourceManager
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app import agent as agent_module
from app.mock_llm import cost_details
from app.prompt_management import ResolvedPrompt
from app.tracing import mask_pii_in_spans

PII_MESSAGE = "What is your refund policy? My email is student@vinuni.edu.vn"


@pytest.fixture
def langfuse_spans(monkeypatch):
    # Client giữ span trong bộ nhớ, không gửi mạng. Reset singleton để get_client()
    # trong app trả về đúng client này thay vì client do test khác tạo ra.
    LangfuseResourceManager.reset()
    exporter = InMemorySpanExporter()
    client = Langfuse(
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        base_url="http://127.0.0.1:9",
        span_exporter=exporter,
        mask_otel_spans=mask_pii_in_spans,
    )
    monkeypatch.setattr(agent_module, "tracing_enabled", lambda: False)

    def finished_spans():
        client.flush()
        return {span.name: span for span in exporter.get_finished_spans()}

    yield client, finished_spans
    LangfuseResourceManager.reset()


def test_agent_trace_has_retrieval_and_generation_children(langfuse_spans) -> None:
    _, finished_spans = langfuse_spans

    agent_module.LabAgent().run(
        user_id="u01",
        feature="qa",
        session_id="s01",
        message=PII_MESSAGE,
        correlation_id="req-1234abcd",
    )
    spans = finished_spans()

    root = spans["lab-agent-run"]
    retrieval = spans["retrieve-context"]
    generation = spans["generate-answer"]
    assert retrieval.parent.span_id == root.context.span_id
    assert generation.parent.span_id == root.context.span_id
    assert root.attributes["langfuse.observation.type"] == "agent"
    assert retrieval.attributes["langfuse.observation.type"] == "retriever"
    assert generation.attributes["langfuse.observation.type"] == "generation"
    assert root.attributes["langfuse.trace.metadata.correlation_id"] == "req-1234abcd"

    gen = generation.attributes
    usage = json.loads(gen["langfuse.observation.usage_details"])
    assert gen["langfuse.observation.model.name"] == "claude-sonnet-4-5"
    assert json.loads(gen["langfuse.observation.cost_details"]) == pytest.approx(
        cost_details(usage["input"], usage["output"])
    )
    assert "langfuse.observation.completion_start_time" in gen

    exported = json.dumps([dict(span.attributes) for span in spans.values()], default=str)
    assert "student@vinuni.edu.vn" not in exported
    assert "[REDACTED_EMAIL]" in root.attributes["langfuse.observation.input"]
    assert root.attributes["langfuse.observation.output"]


def test_managed_prompt_is_linked_to_generation_only(langfuse_spans, monkeypatch) -> None:
    _, finished_spans = langfuse_spans
    managed = ResolvedPrompt(
        text="Feature=qa\nDocs=x\nQuestion=y",
        name="day13-chat",
        label="production",
        version="2",
        source="langfuse",
        managed_prompt={"name": "day13-chat", "version": 2},
    )
    monkeypatch.setattr(agent_module, "resolve_prompt", lambda *args, **kwargs: managed)

    agent_module.LabAgent().run(
        user_id="u01", feature="qa", session_id="s01", message="hi", correlation_id="req-1"
    )
    spans = finished_spans()

    generation = spans["generate-answer"].attributes
    assert generation["langfuse.observation.prompt.name"] == "day13-chat"
    assert generation["langfuse.observation.prompt.version"] == 2
    assert "langfuse.observation.prompt.name" not in spans["retrieve-context"].attributes
    assert spans["lab-agent-run"].attributes["langfuse.version"] == "2"


def test_export_hook_masks_raw_pii_but_keeps_cost_numbers(langfuse_spans) -> None:
    client, finished_spans = langfuse_spans

    with client.start_as_current_observation(
        name="raw-io",
        as_type="generation",
        input="call me at 0987654321",
        cost_details={"input": 0.001234567},  # 0.+9 chữ số: dễ bị nhận nhầm là SĐT
    ):
        pass
    attributes = finished_spans()["raw-io"].attributes

    assert attributes["langfuse.observation.input"] == "call me at [REDACTED_PHONE_VN]"
    assert json.loads(attributes["langfuse.observation.cost_details"]) == {"input": 0.001234567}
