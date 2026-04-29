"""Completion client backed by the Claude Code CLI in one-shot print mode."""

import subprocess


class ClaudeCliCompletionClient:
    """Invoke `claude -p` for single-turn judge completions."""

    __slots__ = ("_command",)

    def __init__(self, *, command: str = "claude") -> None:
        self._command = command

    def complete(self, *, system: str, user: str, model: str, max_tokens: int) -> str:
        _ = max_tokens
        result = subprocess.run(
            [
                self._command,
                "-p",
                "--model",
                model,
                "--system-prompt",
                system,
                "--output-format",
                "text",
                user,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
