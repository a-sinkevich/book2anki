"""LLM provider that calls the claude CLI (claude -p)."""

import os
import shutil
import subprocess
import tempfile
import threading

from book2anki.generator import LLMProvider
from book2anki.models import TokenUsage

# Track all active child processes for cleanup on interrupt
_active_procs: list[subprocess.Popen] = []  # type: ignore[type-arg]
_active_lock = threading.Lock()


def kill_all() -> None:
    """Kill all active claude subprocesses."""
    with _active_lock:
        for proc in list(_active_procs):
            try:
                proc.kill()
            except OSError:
                pass
        _active_procs.clear()


class CLIProvider(LLMProvider):
    def __init__(self, model: str = "opus") -> None:
        self.model = model

    @staticmethod
    def is_available() -> bool:
        """Check if the claude CLI is installed and not inside a nested session."""
        if os.environ.get("CLAUDECODE"):
            return False
        return shutil.which("claude") is not None

    def generate(self, prompt: str) -> tuple[str, TokenUsage]:
        # Write prompt to temp file to avoid ARG_MAX limits.
        # Then ask claude to read the file (claude -p doesn't read from stdin).
        fd, prompt_path = tempfile.mkstemp(suffix=".txt", prefix="book2anki_")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(prompt)

            env = os.environ.copy()
            env.pop("CLAUDECODE", None)

            meta_prompt = (
                f"Read the file at {prompt_path} and follow the instructions inside it exactly. "
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
                start_new_session=True,  # isolate from terminal SIGINT
            )

            with _active_lock:
                _active_procs.append(proc)

            try:
                stdout, stderr = proc.communicate(timeout=600)
            except KeyboardInterrupt:
                proc.kill()
                proc.wait()
                raise
            finally:
                with _active_lock:
                    if proc in _active_procs:
                        _active_procs.remove(proc)

            if proc.returncode != 0:
                raise RuntimeError(
                    f"claude CLI failed: {stderr.strip()}")
            return stdout, TokenUsage(0, 0)
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
