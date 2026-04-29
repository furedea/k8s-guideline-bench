"""Completion client Protocol shared across agent and judge stages."""

from typing import Protocol


class CompletionClient(Protocol):
    """Narrow single-turn chat completion contract."""

    def complete(self, *, system: str, user: str, model: str, max_tokens: int) -> str: ...
