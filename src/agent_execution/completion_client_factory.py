"""Factory that instantiates a CompletionClient from a ClientSpec."""

import os

import anthropic_client
import claude_cli_client
import client_spec
import completion_client
import openai_compatible_client


def build_completion_client(spec: client_spec.ClientSpec) -> completion_client.CompletionClient:
    """Construct a CompletionClient matching the transport dialect in `spec`.

    API-backed clients resolve credentials from the environment variable named
    `spec.api_key_env`. Claude CLI uses local Claude Code authentication.
    """
    if spec.client_type == client_spec.ClientType.CLAUDE_CLI:
        return claude_cli_client.ClaudeCliCompletionClient(command=spec.command)

    if spec.api_key_env is None:
        msg = f"Client type {spec.client_type!r} requires `api_key_env`."
        raise RuntimeError(msg)
    credential = os.environ.get(spec.api_key_env)
    if not credential:
        msg = f"Environment variable {spec.api_key_env!r} is not set."
        raise RuntimeError(msg)

    if spec.client_type == client_spec.ClientType.ANTHROPIC:
        anthropic_kwargs = {"api_key": credential, "base_url": spec.base_url}
        return anthropic_client.AnthropicCompletionClient(**anthropic_kwargs)

    if spec.client_type == client_spec.ClientType.OPENAI_COMPATIBLE:
        return _build_openai_compatible(spec, credential)

    msg = f"Unsupported client type: {spec.client_type!r}"
    raise ValueError(msg)


def _build_openai_compatible(
    spec: client_spec.ClientSpec,
    credential: str,
) -> openai_compatible_client.OpenAICompatibleCompletionClient:
    if spec.base_url is None:
        msg = "OpenAI-compatible client requires `base_url` in ClientSpec."
        raise ValueError(msg)
    kwargs = {"api_key": credential, "base_url": spec.base_url}
    return openai_compatible_client.OpenAICompatibleCompletionClient(**kwargs)  # ty: ignore[invalid-argument-type]
