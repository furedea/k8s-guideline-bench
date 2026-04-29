"""Tests for OpenAICompatibleCompletionClient adapter."""

from unittest.mock import MagicMock

import httpx
import openai_compatible_client


def test_openai_compatible_client_posts_chat_completion_with_bearer_auth() -> None:
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.json.return_value = {"choices": [{"message": {"content": "hello"}}]}
    mock_http = MagicMock(spec=httpx.Client)
    mock_http.post.return_value = mock_response

    client = openai_compatible_client.OpenAICompatibleCompletionClient(
        api_key="sk-test",
        base_url="https://opencode.ai/zen/go/v1",
        http_client=mock_http,
    )
    result = client.complete(
        system="sys-prompt",
        user="user-prompt",
        model="kimi-k2-thinking",
        max_tokens=1024,
    )

    assert result == "hello"
    mock_http.post.assert_called_once()
    call = mock_http.post.call_args
    assert call.args[0] == "https://opencode.ai/zen/go/v1/chat/completions"
    assert call.kwargs["headers"]["Authorization"] == "Bearer sk-test"
    assert call.kwargs["json"]["model"] == "kimi-k2-thinking"
    assert call.kwargs["json"]["max_tokens"] == 1024
    assert call.kwargs["json"]["messages"] == [
        {"role": "system", "content": "sys-prompt"},
        {"role": "user", "content": "user-prompt"},
    ]


def test_openai_compatible_client_strips_trailing_slash_from_base_url() -> None:
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    mock_http = MagicMock(spec=httpx.Client)
    mock_http.post.return_value = mock_response

    client = openai_compatible_client.OpenAICompatibleCompletionClient(
        api_key="sk-test",
        base_url="https://opencode.ai/zen/go/v1/",
        http_client=mock_http,
    )
    _ = client.complete(system="s", user="u", model="m", max_tokens=1)

    assert mock_http.post.call_args.args[0] == "https://opencode.ai/zen/go/v1/chat/completions"


def test_openai_compatible_client_raises_for_http_errors() -> None:
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "boom",
        request=MagicMock(spec=httpx.Request),
        response=mock_response,
    )
    mock_http = MagicMock(spec=httpx.Client)
    mock_http.post.return_value = mock_response

    client = openai_compatible_client.OpenAICompatibleCompletionClient(
        api_key="sk-test",
        base_url="https://opencode.ai/zen/go/v1",
        http_client=mock_http,
    )

    try:
        _ = client.complete(system="s", user="u", model="m", max_tokens=1)
    except httpx.HTTPStatusError:
        return
    msg = "HTTPStatusError should propagate"
    raise AssertionError(msg)
