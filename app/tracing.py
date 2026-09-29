from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any

from .pii import scrub_text

try:
    from langfuse import Langfuse, get_client, observe, propagate_attributes
    from langfuse.types import MaskOtelSpansParams, MaskOtelSpansResult, OtelSpanPatch

    LANGFUSE_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - chỉ dùng khi chưa cài dependencies
    LANGFUSE_SDK_AVAILABLE = False

    def observe(*args: Any, **kwargs: Any):
        def decorator(func):
            return func

        return decorator

    class _DummyClient:
        def update_current_span(self, **kwargs: Any) -> None:
            return None

        def update_current_generation(self, **kwargs: Any) -> None:
            return None

        def flush(self) -> None:
            return None

    def get_client():
        return _DummyClient()

    @contextmanager
    def propagate_attributes(**kwargs: Any):
        yield


# Chỉ quét attribute mang dữ liệu người dùng; bỏ qua usage/cost/model để regex PII
# không làm hỏng số liệu (ví dụ số thập phân dài bị nhận nhầm là số điện thoại).
_PII_ATTRIBUTE_PREFIXES = (
    "langfuse.trace.input",
    "langfuse.trace.output",
    "langfuse.trace.metadata",
    "langfuse.observation.input",
    "langfuse.observation.output",
    "langfuse.observation.metadata",
    "langfuse.observation.status_message",
)


def mask_pii_in_spans(*, params: MaskOtelSpansParams) -> MaskOtelSpansResult | None:
    """Lưới an toàn ở tầng export: che PII còn sót trước khi span rời process."""
    patches = {}
    for identifier, span in params.spans.items():
        replacements = {}
        for key, value in span.attributes.items():
            if isinstance(value, str) and key.startswith(_PII_ATTRIBUTE_PREFIXES):
                masked = scrub_text(value)
                if masked != value:
                    replacements[key] = masked
        if replacements:
            patches[identifier] = OtelSpanPatch(set_attributes=replacements)
    return MaskOtelSpansResult(span_patches=patches) if patches else None


def init_tracing() -> bool:
    """Tạo Langfuse client có hook che PII.

    Phải gọi trước observation đầu tiên: get_client() trả về singleton đã tạo,
    nên client tạo sau đó sẽ không có hook.
    """
    if not tracing_enabled():
        return False
    Langfuse(mask_otel_spans=mask_pii_in_spans)
    return True


def flush_tracing() -> None:
    if tracing_enabled():
        get_client().flush()


def get_langfuse_client():
    return get_client()


def tracing_enabled() -> bool:
    return LANGFUSE_SDK_AVAILABLE and bool(
        os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")
    )
