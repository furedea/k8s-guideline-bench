"""OpenAI-compatible local LLM proxy for request-time model options."""

import argparse
import json
import logging
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import urljoin

import httpx

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8002
DEFAULT_UPSTREAM_BASE_URL = "http://localhost:8001/v1"
DEFAULT_TIMEOUT_SECONDS = 300.0
CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
JSON_CONTENT_TYPE = "application/json"


def inject_thinking_disabled(document: Mapping[str, Any]) -> dict[str, Any]:
    """Return a request body that disables Qwen thinking through the chat template."""
    injected = dict(document)
    raw_kwargs = injected.get("chat_template_kwargs", {})
    chat_template_kwargs = dict(cast("Mapping[str, Any]", raw_kwargs))
    chat_template_kwargs["enable_thinking"] = False
    injected["chat_template_kwargs"] = chat_template_kwargs
    return injected


def forward_chat_completion(
    *,
    upstream_base_url: str,
    request_headers: Mapping[str, str],
    request_body: bytes,
    http_client: httpx.Client,
) -> httpx.Response:
    document = json.loads(request_body)
    injected = inject_thinking_disabled(cast("Mapping[str, Any]", document))
    return http_client.post(
        _upstream_url(upstream_base_url, CHAT_COMPLETIONS_PATH),
        headers=dict(request_headers),
        content=json.dumps(injected, separators=(",", ":")).encode("utf-8"),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a local OpenAI-compatible proxy for SGLang.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--upstream", default=DEFAULT_UPSTREAM_BASE_URL)
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    run_proxy(
        host=str(arguments.host),
        port=int(arguments.port),
        upstream_base_url=str(arguments.upstream),
    )


def run_proxy(*, host: str, port: int, upstream_base_url: str) -> None:
    with httpx.Client(timeout=DEFAULT_TIMEOUT_SECONDS) as http_client:
        handler = _make_handler(upstream_base_url.rstrip("/"), http_client)
        server = ThreadingHTTPServer((host, port), handler)
        logger.info({"action": "local_llm_proxy_start", "host": host, "port": port, "upstream": upstream_base_url})
        server.serve_forever()


def _make_handler(
    upstream_base_url: str,
    http_client: httpx.Client,
) -> type[BaseHTTPRequestHandler]:
    class LocalLLMProxyHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._forward_without_body()

        def do_POST(self) -> None:
            request_body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            request_headers = _forward_headers(cast("Mapping[str, str]", self.headers))
            if self.path == CHAT_COMPLETIONS_PATH:
                response = forward_chat_completion(
                    upstream_base_url=upstream_base_url,
                    request_headers=request_headers,
                    request_body=request_body,
                    http_client=http_client,
                )
            else:
                response = http_client.post(
                    _upstream_url(upstream_base_url, self.path),
                    headers=request_headers,
                    content=request_body,
                )
            self._write_response(response)

        def log_message(self, format: str, *args: object) -> None:
            logger.info({"action": "local_llm_proxy_request", "message": format % args})

        def _forward_without_body(self) -> None:
            response = http_client.get(
                _upstream_url(upstream_base_url, self.path),
                headers=_forward_headers(cast("Mapping[str, str]", self.headers)),
            )
            self._write_response(response)

        def _write_response(self, response: httpx.Response) -> None:
            self.send_response(response.status_code)
            content_type = response.headers.get("Content-Type", JSON_CONTENT_TYPE)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)

    return LocalLLMProxyHandler


def _forward_headers(headers: Mapping[str, str]) -> dict[str, str]:
    excluded = {"host", "content-length"}
    return {key: value for key, value in headers.items() if key.lower() not in excluded}


def _upstream_url(upstream_base_url: str, path: str) -> str:
    upstream_path = path.removeprefix("/v1/")
    return urljoin(f"{upstream_base_url.rstrip('/')}/", upstream_path)


if __name__ == "__main__":
    main()
