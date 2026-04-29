"""Tests for AnthropicCompletionClient adapter."""

from unittest.mock import MagicMock

import anthropic_client
from pytest_mock import MockerFixture


def test_anthropic_client_forwards_base_url_to_sdk(mocker: MockerFixture) -> None:
    mock_sdk = mocker.patch("anthropic_client.anthropic.Anthropic")

    _ = anthropic_client.AnthropicCompletionClient(
        api_key="dummy",
        base_url="https://opencode.ai/zen/go",
    )

    mock_sdk.assert_called_once_with(api_key="dummy", base_url="https://opencode.ai/zen/go")


def test_anthropic_client_omits_base_url_when_none(mocker: MockerFixture) -> None:
    mock_sdk = mocker.patch("anthropic_client.anthropic.Anthropic")

    _ = anthropic_client.AnthropicCompletionClient(api_key="dummy")

    mock_sdk.assert_called_once_with(api_key="dummy")


def test_anthropic_client_complete_returns_concatenated_text(mocker: MockerFixture) -> None:
    mock_sdk_class = mocker.patch("anthropic_client.anthropic.Anthropic")
    mock_text_block = MagicMock()
    mock_text_block.type = "text"
    mock_text_block.text = "hello"
    mock_other_block = MagicMock()
    mock_other_block.type = "tool_use"
    mock_message = MagicMock()
    mock_message.content = [mock_text_block, mock_other_block]
    mock_sdk_class.return_value.messages.create.return_value = mock_message

    client = anthropic_client.AnthropicCompletionClient(api_key="dummy")
    result = client.complete(system="sys", user="usr", model="claude-haiku-4-5", max_tokens=100)

    assert result == "hello"
    mock_sdk_class.return_value.messages.create.assert_called_once_with(
        model="claude-haiku-4-5",
        max_tokens=100,
        system="sys",
        messages=[{"role": "user", "content": "usr"}],
    )
