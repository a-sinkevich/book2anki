import os
import sys

from book2anki.generator import LLMProvider
from book2anki.models import TokenUsage


class OpenAIProvider(LLMProvider):
    def __init__(self) -> None:
        try:
            import openai
        except ImportError:
            print(
                "Error: OpenAI models require the openai package, which is not\n"
                "available in the standalone binary.\n\n"
                "To use GPT models, run from source:\n"
                "  pip install -e '.[openai]'\n"
                "  python -m book2anki mybook.epub --model gpt5.5\n\n"
                "The standalone binary supports Claude models (default) and CLI providers.",
                file=sys.stderr,
            )
            sys.exit(1)

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

    def generate(self, prompt: str) -> tuple[str, TokenUsage]:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
        )
        choice = response.choices[0]
        if choice.finish_reason == "content_filter":
            raise ValueError("Model refused the request (content_filter)")
        text = choice.message.content or ""
        usage = TokenUsage(
            input_tokens=response.usage.prompt_tokens if response.usage else 0,
            output_tokens=response.usage.completion_tokens if response.usage else 0,
        )
        return text, usage

    def model_name(self) -> str:
        return self.model

    def context_window_tokens(self) -> int:
        return 128_000

    def max_request_tokens(self) -> int:
        return 100_000
