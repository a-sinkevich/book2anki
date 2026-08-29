import os
import sys

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
            if sys.platform == "win32":
                env_path = r"C:\Users\<YourName>\.book2anki.env"
            else:
                env_path = "~/.book2anki.env"
            raise ValueError(
                "ANTHROPIC_API_KEY is not set.\n\n"
                "1. Get an API key at: https://console.anthropic.com/settings/keys\n"
                "2. Add credit at: https://console.anthropic.com/settings/billing\n"
                f"3. Save the key in {env_path}:\n"
                "   ANTHROPIC_API_KEY=sk-ant-...\n"
            )

        self.model = "claude-sonnet-4-6"

    def set_model(self, model_name: str) -> None:
        """Switch to a different model."""
        models = {
            "sonnet": "claude-sonnet-4-6",
            "opus": "claude-opus-4-8",
        }
        self.model = models.get(model_name, model_name)

    def generate(self, prompt: str) -> tuple[str, TokenUsage]:
        # Stream, don't wait: a comprehensive chapter can take the model
        # minutes to answer, and a non-streaming request that long gets its
        # idle connection dropped (APIConnectionError) before the reply lands.
        with self.client.messages.stream(
            model=self.model,
            max_tokens=64000,
            messages=[{"role": "user", "content": prompt}],
        ) as stream:
            response = stream.get_final_message()
        usage = TokenUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )
        if response.stop_reason == "refusal":
            raise ValueError("Model refused the request (stop_reason=refusal)")
        # Find the first TextBlock — some models return ThinkingBlock(s) first
        for block in response.content:
            if hasattr(block, "text"):
                return block.text, usage
        raise ValueError(
            f"No text in response, got: "
            f"{[type(b).__name__ for b in response.content]}"
        )

    def model_name(self) -> str:
        return self.model

    def context_window_tokens(self) -> int:
        return 200_000

    def max_request_tokens(self) -> int:
        return 100_000
