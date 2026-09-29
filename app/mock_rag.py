from __future__ import annotations

import time

from .incidents import STATE
from .pii import scrub_text
from .tracing import get_langfuse_client, observe

CORPUS = {
    "refund": ["Refunds are available within 7 days with proof of purchase."],
    "monitoring": ["Metrics detect incidents, logs identify affected requests, traces localize the root cause."],
    "policy": ["Do not expose PII in logs. Use sanitized summaries only."],
}
FALLBACK_DOCS = ["No domain document matched. Use general fallback answer."]


@observe(name="retrieve-context", as_type="retriever", capture_input=False, capture_output=False)
def retrieve(message: str) -> list[str]:
    langfuse_client = get_langfuse_client()
    # Ghi input trước khi gọi vector store để trace lỗi vẫn thấy query nào gây sự cố.
    langfuse_client.update_current_span(input={"query": scrub_text(message)})
    if STATE["tool_fail"]:
        raise RuntimeError("Vector store timeout")
    if STATE["rag_slow"]:
        time.sleep(2.5)
    lowered = message.lower()
    matched_topic = next((key for key in CORPUS if key in lowered), None)
    docs = CORPUS[matched_topic] if matched_topic else FALLBACK_DOCS
    langfuse_client.update_current_span(
        output={"documents": docs},
        metadata={"matched_topic": matched_topic or "none", "doc_count": len(docs)},
    )
    return docs
