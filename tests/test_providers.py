from book2anki.provider_cli import CLIProvider
from book2anki.provider_codex import CodexCLIProvider


def test_claude_cli_model_name_uses_exact_alias():
    assert CLIProvider("opus").model_name() == "cli:claude-opus-5"
    assert CLIProvider("sonnet").model_name() == "cli:claude-sonnet-5"


def test_codex_cli_passes_reported_model(monkeypatch):
    seen: dict[str, list[str]] = {}

    class FakeProc:
        returncode = 0

        def __init__(self, cmd, **_kwargs):
            seen["cmd"] = cmd

        def communicate(self, timeout):
            return "[]", ""

    monkeypatch.setattr("book2anki.provider_codex.subprocess.Popen", FakeProc)

    provider = CodexCLIProvider("gpt-5.5")
    text = provider.generate("prompt")

    assert text == "[]"
    assert provider.model_name() == "codex:gpt-5.5"
    assert seen["cmd"] == [
        "codex", "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--model", "gpt-5.5",
        "-",
    ]
