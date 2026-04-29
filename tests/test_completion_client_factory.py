"""Tests for completion_client_factory."""

import client_spec
import completion_client_factory
import pytest
from pytest_mock import MockerFixture


def test_factory_builds_anthropic_client_with_base_url(mocker: MockerFixture) -> None:
    mock_anthropic = mocker.patch("completion_client_factory.anthropic_client.AnthropicCompletionClient")
    monkeypatch_env = mocker.patch.dict(
        "os.environ",
        {"OPENCODE_API_KEY": "dummy"},
    )
    _ = monkeypatch_env

    spec = client_spec.ClientSpec(
        client_type=client_spec.ClientType.ANTHROPIC,
        api_key_env="OPENCODE_API_KEY",
        base_url="https://opencode.ai/zen/go",
    )
    _ = completion_client_factory.build_completion_client(spec)

    mock_anthropic.assert_called_once_with(api_key="dummy", base_url="https://opencode.ai/zen/go")


def test_factory_builds_openai_compatible_client(mocker: MockerFixture) -> None:
    mock_openai = mocker.patch(
        "completion_client_factory.openai_compatible_client.OpenAICompatibleCompletionClient",
    )
    _ = mocker.patch.dict("os.environ", {"OPENCODE_API_KEY": "dummy"})

    spec = client_spec.ClientSpec(
        client_type=client_spec.ClientType.OPENAI_COMPATIBLE,
        api_key_env="OPENCODE_API_KEY",
        base_url="https://opencode.ai/zen/go/v1",
    )
    _ = completion_client_factory.build_completion_client(spec)

    mock_openai.assert_called_once_with(
        api_key="dummy",
        base_url="https://opencode.ai/zen/go/v1",
    )


def test_factory_builds_claude_cli_client_without_api_key(mocker: MockerFixture) -> None:
    mock_claude = mocker.patch("completion_client_factory.claude_cli_client.ClaudeCliCompletionClient")
    _ = mocker.patch.dict("os.environ", {}, clear=True)

    spec = client_spec.ClientSpec(
        client_type=client_spec.ClientType.CLAUDE_CLI,
        command="claude",
    )
    _ = completion_client_factory.build_completion_client(spec)

    mock_claude.assert_called_once_with(command="claude")


def test_factory_raises_when_env_var_missing(mocker: MockerFixture) -> None:
    _ = mocker.patch.dict("os.environ", {}, clear=True)
    spec = client_spec.ClientSpec(
        client_type=client_spec.ClientType.ANTHROPIC,
        api_key_env="MISSING_KEY_NAME",
    )

    with pytest.raises(RuntimeError, match="MISSING_KEY_NAME"):
        _ = completion_client_factory.build_completion_client(spec)


def test_factory_raises_when_openai_compatible_lacks_base_url(mocker: MockerFixture) -> None:
    _ = mocker.patch.dict("os.environ", {"K": "dummy"})
    spec = client_spec.ClientSpec(
        client_type=client_spec.ClientType.OPENAI_COMPATIBLE,
        api_key_env="K",
    )

    with pytest.raises(ValueError, match="base_url"):
        _ = completion_client_factory.build_completion_client(spec)
