from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from .incidents import STATE
from .pii import scrub_text
from .tracing import get_langfuse_client, observe

# Giá tham chiếu của claude-sonnet-4-5 (USD / 1M tokens).
INPUT_USD_PER_MTOK = 3
OUTPUT_USD_PER_MTOK = 15


def cost_details(input_tokens: int, output_tokens: int) -> dict[str, float]:
    return {
        "input": (input_tokens / 1_000_000) * INPUT_USD_PER_MTOK,
        "output": (output_tokens / 1_000_000) * OUTPUT_USD_PER_MTOK,
    }


@dataclass
class FakeUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class FakeResponse:
    text: str
    usage: FakeUsage
    model: str
    ttft_ms: int


class FakeLLM:
    def __init__(self, model: str = "claude-sonnet-4-5") -> None:
        self.model = model

    @observe(name="generate-answer", as_type="generation", capture_input=False, capture_output=False)
    def generate(self, prompt: str) -> FakeResponse:
        langfuse_client = get_langfuse_client()
        langfuse_client.update_current_generation(
            model=self.model,
            input=[{"role": "user", "content": scrub_text(prompt)}],
        )
        started = time.perf_counter()
        time.sleep(0.05)  # mô phỏng thời điểm token đầu tiên sẵn sàng
        first_token_at = datetime.now(timezone.utc)
        ttft_ms = int((time.perf_counter() - started) * 1000)
        time.sleep(0.10)
        input_tokens = max(20, len(prompt) // 4)
        output_tokens = random.randint(80, 180)
        if STATE["cost_spike"]:
            output_tokens *= 4
        answer = (
            "Starter answer. You should improve this output logic and add better quality checks. "
            "Use retrieved context and keep responses concise."
        )
        langfuse_client.update_current_generation(
            output={"role": "assistant", "content": scrub_text(answer)},
            completion_start_time=first_token_at,  # Langfuse tính TTFT từ mốc này
            usage_details={"input": input_tokens, "output": output_tokens},
            cost_details=cost_details(input_tokens, output_tokens),
        )
        return FakeResponse(
            text=answer,
            usage=FakeUsage(input_tokens, output_tokens),
            model=self.model,
            ttft_ms=ttft_ms,
        )
