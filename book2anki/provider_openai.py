import os
import sys

import openai

from book2anki.generator import LLMProvider


class OpenAIProvider(LLMProvider):
    def __init__(self) -> None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            if sys.platform == "win32":
                env_path = r"C:\Users\<YourName>\.book2anki.env"
            else:
                env_path = "~/.book2anki.env"
            raise ValueError(
                "OPENAI_API_KEY is not set.\n\n"
                "1. Get an API key at: https://platform.openai.com/api-keys\n"
                f"2. Save the key in {env_path}:\n"
                "   OPENAI_API_KEY=sk-...\n"
            )

        self.client = openai.OpenAI(api_key=api_key, timeout=1800.0)
        self.model = "gpt-5.5"

    def set_model(self, model_name: str) -> None:
        """Switch to a different model."""
        models = {
            "gpt5.5": "gpt-5.5",
            "gpt5.4": "gpt-5.4",
            "gpt5.4-mini": "gpt-5.4-mini",
            "gpt4o": "gpt-4o",
            "gpt4o-mini": "gpt-4o-mini",
            "o3": "o3",
            "o3-mini": "o3-mini",
            "o4-mini": "o4-mini",
        }
        self.model = models.get(model_name, model_name)

    def generate(self, prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
        )
        choice = response.choices[0]
        if choice.finish_reason == "content_filter":
            raise ValueError("Model refused the request (content_filter)")
        text: str = choice.message.content or ""
        return text

    def model_name(self) -> str:
        return self.model

    def context_window_tokens(self) -> int:
        return 128_000

    def max_request_tokens(self) -> int:
        return 100_000
