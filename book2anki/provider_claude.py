import os

import anthropic

from book2anki.generator import LLMProvider
from book2anki.models import TokenUsage


class ClaudeProvider(LLMProvider):
    def __init__(self) -> None:
        base_url = os.environ.get("ANTHROPIC_VERTEX_BASE_URL")
        api_key = os.environ.get("ANTHROPIC_API_KEY")

        if base_url:
            if base_url.endswith("/v1"):
                base_url = base_url[:-3]
            self.client = anthropic.Anthropic(
                base_url=base_url,
                api_key="unused",  # Vertex proxy handles auth
                timeout=1800.0,
            )
        elif api_key:
            self.client = anthropic.Anthropic(api_key=api_key, timeout=1800.0)
        else:
            raise ValueError(
                "Set ANTHROPIC_API_KEY in ~/.book2anki.env or as an environment variable."
            )

        self.model = "claude-sonnet-4-6"

    def generate(self, prompt: str) -> tuple[str, TokenUsage]:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=16384,
            messages=[{"role": "user", "content": prompt}],
        )
        block = response.content[0]
        assert hasattr(block, "text"), f"Expected TextBlock, got {type(block)}"
        usage = TokenUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        return block.text, usage

    def model_name(self) -> str:
        return self.model

    def context_window_tokens(self) -> int:
        return 200_000

    def max_request_tokens(self) -> int:
        return 100_000
