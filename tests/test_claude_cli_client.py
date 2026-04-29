"""Tests for Claude CLI completion client."""

from subprocess import CompletedProcess

import claude_cli_client
from pytest_mock import MockerFixture


def test_claude_cli_client_invokes_print_mode_with_system_prompt_and_model(
    mocker: MockerFixture,
) -> None:
    run = mocker.patch(
        "claude_cli_client.subprocess.run",
        autospec=True,
        return_value=CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"verdict": "compliant"}',
            stderr="",
        ),
    )
    client = claude_cli_client.ClaudeCliCompletionClient(command="claude")

    response = client.complete(
        system="judge system",
        user="judge user",
        model="sonnet",
        max_tokens=1024,
    )

    assert response == '{"verdict": "compliant"}'
    assert run.call_args.args[0] == [
        "claude",
        "-p",
        "--model",
        "sonnet",
        "--system-prompt",
        "judge system",
        "--output-format",
        "text",
        "judge user",
    ]
