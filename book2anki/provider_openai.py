import os

import openai

from book2anki.generator import LLMProvider
from book2anki.models import TokenUsage


class OpenAIProvider(LLMProvider):
    def __init__(self) -> None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("Set OPENAI_API_KEY in ~/.book2anki.env or as an environment variable.")
        self.client = openai.OpenAI(api_key=api_key)
        self.model = "gpt-4o"

    def generate(self, prompt: str) -> tuple[str, TokenUsage]:
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
        )
        usage = response.usage
        token_usage = TokenUsage(
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )
        return response.choices[0].message.content or "", token_usage

    def model_name(self) -> str:
        return self.model

    def context_window_tokens(self) -> int:
        return 128_000
