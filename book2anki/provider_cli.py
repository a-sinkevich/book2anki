"""LLM provider that calls the claude CLI (claude -p)."""

import os
import shutil
import subprocess
import tempfile

from book2anki.generator import LLMProvider


class CLIProvider(LLMProvider):
    def __init__(self, model: str = "opus") -> None:
        models = {
            "sonnet": "claude-sonnet-4-6",
            "opus": "claude-opus-4-8",
        }
        self.model = models.get(model, model)

    @staticmethod
    def is_available() -> bool:
        """Check if the claude CLI is installed and not inside a nested session."""
        if os.environ.get("CLAUDECODE"):
            return False
        return shutil.which("claude") is not None

    def generate(self, prompt: str) -> str:
        # Write prompt to temp file to avoid ARG_MAX limits.
        # Then ask claude to read the file (claude -p doesn't read from stdin).
        # Use system temp dir so the claude CLI doesn't pick up the project's
        # .claude/ directory and load extra context, which can cause slowdowns.
        fd, prompt_path = tempfile.mkstemp(
            suffix=".txt", prefix=".book2anki_",
        )
        prompt_abs = os.path.abspath(prompt_path)
        # Run claude from the temp file's directory to avoid project detection.
        cwd = os.path.dirname(prompt_abs)
        try:
            with os.fdopen(fd, "w") as f:
                f.write(prompt)

            env = os.environ.copy()
            env.pop("CLAUDECODE", None)

            meta_prompt = (
                f"Read the file at {prompt_abs} and follow the instructions inside it exactly. "
                f"Output only what the instructions ask for — no extra commentary."
            )

            proc = subprocess.Popen(
                [
                    "claude", "-p", meta_prompt,
                    "--model", self.model,
                    "--no-session-persistence",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
                cwd=cwd,
            )

            stdout, stderr = proc.communicate(timeout=600)

            if proc.returncode != 0:
                raise RuntimeError(
                    f"claude CLI failed: {stderr.strip()}")
            return stdout
        finally:
            try:
                os.unlink(prompt_path)
            except OSError:
                pass

    def model_name(self) -> str:
        return f"cli:{self.model}"

    def context_window_tokens(self) -> int:
        return 200_000

    def max_request_tokens(self) -> int:
        return 100_000
