"""Completion client backed by the Claude Code CLI in one-shot print mode."""

import subprocess


class ClaudeCliFatalError(RuntimeError):
    """`claude -p` exited with a non-zero status.

    Treated as fatal because retrying after auth, quota, or model-config
    failures would amplify the same error and burn quota; the run should
    surface the diagnosis (returncode + stdout/stderr) and stop. The user
    prompt is intentionally excluded from the message so failure logs
    cannot leak the patch under judgment.
    """

    __slots__ = ("returncode", "stderr", "stdout")

    def __init__(self, *, returncode: int, stdout: str, stderr: str) -> None:
        super().__init__(f"claude CLI exited with returncode={returncode}")
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


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
            check=False,
        )
        if result.returncode != 0:
            raise ClaudeCliFatalError(
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        return result.stdout
