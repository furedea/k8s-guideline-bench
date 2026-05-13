"""Tests for the local OpenAI-compatible proxy."""

import httpx
from pytest_mock import MockerFixture

import local_llm_proxy


def test_inject_thinking_disabled_adds_qwen_chat_template_flag() -> None:
    document = {
        "model": "Qwen/Qwen3.6-27B-FP8",
        "messages": [{"role": "user", "content": "hello"}],
    }

    injected = local_llm_proxy.inject_thinking_disabled(document)

    assert injected == {
        "model": "Qwen/Qwen3.6-27B-FP8",
        "messages": [{"role": "user", "content": "hello"}],
        "chat_template_kwargs": {"enable_thinking": False},
    }
    assert document == {
        "model": "Qwen/Qwen3.6-27B-FP8",
        "messages": [{"role": "user", "content": "hello"}],
    }


def test_inject_thinking_disabled_preserves_existing_chat_template_kwargs() -> None:
    document = {
        "model": "Qwen/Qwen3.6-27B-FP8",
        "messages": [{"role": "user", "content": "hello"}],
        "chat_template_kwargs": {"foo": "bar", "enable_thinking": True},
    }

    injected = local_llm_proxy.inject_thinking_disabled(document)

    assert injected["chat_template_kwargs"] == {"foo": "bar", "enable_thinking": False}


def test_forward_chat_completion_posts_injected_body_to_upstream(mocker: MockerFixture) -> None:
    upstream_response = httpx.Response(
        status_code=200,
        json={"choices": [{"message": {"content": '{"ok": true}'}}]},
    )
    http_client = mocker.Mock(spec=httpx.Client)
    http_client.post.return_value = upstream_response
    request_headers = {"Authorization": "Bearer local-key", "Content-Type": "application/json"}

    response = local_llm_proxy.forward_chat_completion(
        upstream_base_url="http://localhost:8001/v1",
        request_headers=request_headers,
        request_body=b'{"model":"Qwen/Qwen3.6-27B-FP8","messages":[]}',
        http_client=http_client,
    )

    assert response is upstream_response
    http_client.post.assert_called_once_with(
        "http://localhost:8001/v1/chat/completions",
        headers=request_headers,
        content=b'{"model":"Qwen/Qwen3.6-27B-FP8","messages":[],"chat_template_kwargs":{"enable_thinking":false}}',
    )
