"""The upstream model API (DeepSeek, OpenAI compatible). No retries: the agent retries."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx


class UpstreamError(Exception):
    """The upstream answered with a non 2xx status, or not with a JSON object (502)."""

    def __init__(self, status: int | None) -> None:
        super().__init__(f"upstream failed with status {status}")
        self.status = status


class UpstreamTimeout(Exception):
    """The upstream did not answer within the configured timeout (504)."""


@dataclass(frozen=True)
class UpstreamClient:
    """Sends the masked body with the upstream key and nothing else from the caller."""

    client: httpx.AsyncClient
    api_key: str

    # Any: the request and response are open ended OpenAI JSON.
    async def complete(self, body: Mapping[str, Any]) -> tuple[int, dict[str, Any]]:
        """`(status, json)` of a successful completion; raises on failure or timeout."""
        try:
            response = await self.client.post(
                "/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
        except httpx.TimeoutException as exc:
            raise UpstreamTimeout("upstream timed out") from exc
        except httpx.HTTPError as exc:
            raise UpstreamError(None) from exc
        if not response.is_success:
            raise UpstreamError(response.status_code)
        try:
            parsed = response.json()
        except ValueError as exc:
            raise UpstreamError(response.status_code) from exc
        if not isinstance(parsed, dict):
            raise UpstreamError(response.status_code)
        return response.status_code, parsed
