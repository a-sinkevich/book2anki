"""LLM provider that calls the Codex CLI (codex exec)."""

import os
import shutil
import subprocess
import tempfile

from book2anki.generator import LLMProvider
from book2anki.models import TokenUsage


class CodexCLIProvider(LLMProvider):
    def __init__(self, model: str = "gpt-5.5") -> None:
        self.model = model

    @staticmethod
    def is_available() -> bool:
        """Check if the codex CLI is installed."""
        return shutil.which("codex") is not None

    def generate(self, prompt: str) -> tuple[str, TokenUsage]:
        # Write prompt to temp file to avoid ARG_MAX limits.
        # Pipe it into codex exec via stdin.
        fd, prompt_path = tempfile.mkstemp(
            suffix=".txt", prefix=".book2anki_",
        )
        cwd = os.path.dirname(os.path.abspath(prompt_path))
        try:
            with os.fdopen(fd, "w") as f:
                f.write(prompt)

            with open(prompt_path) as stdin_f:
                proc = subprocess.Popen(
                    [
                        "codex", "exec",
                        "--ephemeral",
                        "--skip-git-repo-check",
                        "--model", self.model,
                        "-",
                    ],
                    stdin=stdin_f,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    cwd=cwd,
                )

                stdout, stderr = proc.communicate(timeout=600)

            if proc.returncode != 0:
                raise RuntimeError(
                    f"codex CLI failed: {stderr.strip()}")
            return stdout, TokenUsage(0, 0)
        finally:
            try:
                os.unlink(prompt_path)
            except OSError:
                pass

    def model_name(self) -> str:
        return f"codex:{self.model}"

    def context_window_tokens(self) -> int:
        return 200_000

    def max_request_tokens(self) -> int:
        return 100_000
