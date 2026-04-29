"""OpenAI-compatible completion client adapter.

Targets OpenCode Zen / OpenCode Go style `/v1/chat/completions` endpoints where
the base URL already includes the `/v1` prefix. A single `httpx.Client` is kept
on the instance so connections are pooled across repeated requests.
"""

import httpx

_DEFAULT_TIMEOUT_SECONDS = 300.0


class OpenAICompatibleCompletionClient:
    """Completion client for any OpenAI-compatible `/chat/completions` endpoint."""

    __slots__ = ("_api_key", "_base_url", "_client")

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = http_client if http_client is not None else httpx.Client(timeout=_DEFAULT_TIMEOUT_SECONDS)

    def complete(self, *, system: str, user: str, model: str, max_tokens: int) -> str:
        """Send a single-turn chat completion and return the concatenated text."""
        response = self._client.post(
            f"{self._base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        response.raise_for_status()
        document = response.json()
        return str(document["choices"][0]["message"]["content"])
