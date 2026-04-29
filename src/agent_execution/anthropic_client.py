"""Anthropic completion client adapter."""

from typing import Any

import anthropic


class AnthropicCompletionClient:
    """Completion client backed by the Anthropic Messages API."""

    __slots__ = ("_client",)

    def __init__(self, *, api_key: str, base_url: str | None = None) -> None:
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url is not None:
            kwargs["base_url"] = base_url
        self._client = anthropic.Anthropic(**kwargs)

    def complete(self, *, system: str, user: str, model: str, max_tokens: int) -> str:
        """Send a single-turn message and return the concatenated text content."""
        message = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in message.content if block.type == "text")  # ty: ignore[unresolved-attribute]
