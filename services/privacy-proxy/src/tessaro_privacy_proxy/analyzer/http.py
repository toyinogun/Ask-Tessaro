"""The Presidio analyzer over HTTP. Any failure fails closed (spec 0006 AC-8)."""

from collections.abc import Sequence
from dataclasses import dataclass

import httpx
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from tessaro_privacy_proxy.masking.entities import ANALYZER_TYPES
from tessaro_privacy_proxy.masking.errors import AnalyzerUnavailable
from tessaro_privacy_proxy.masking.ports import AnalyzerResult


class _Hit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    entity_type: str
    start: int
    end: int
    score: float


_HITS = TypeAdapter(list[_Hit])
_ENTITIES = [str(t) for t in ANALYZER_TYPES]


@dataclass(frozen=True)
class HttpAnalyzer:
    """Calls `POST /analyze` for the four analyzer types, English, at the score threshold."""

    client: httpx.AsyncClient
    score_threshold: float

    async def analyze(self, text: str) -> Sequence[AnalyzerResult]:
        """Hits in `text`; raises `AnalyzerUnavailable` on a network error, timeout or bad reply."""
        payload = {
            "text": text,
            "language": "en",
            "entities": _ENTITIES,
            "score_threshold": self.score_threshold,
        }
        try:
            response = await self.client.post("/analyze", json=payload)
        except httpx.HTTPError as exc:
            raise AnalyzerUnavailable(f"analyzer call failed: {type(exc).__name__}") from exc
        if response.status_code != httpx.codes.OK:
            raise AnalyzerUnavailable(f"analyzer returned {response.status_code}")
        try:
            hits = _HITS.validate_json(response.content)
        except ValidationError as exc:
            raise AnalyzerUnavailable("analyzer reply did not parse") from exc
        return [AnalyzerResult(h.entity_type, h.start, h.end, h.score) for h in hits]

    async def healthy(self) -> bool:
        """Readiness probe: the analyzer's `/health` answers 200."""
        response = await self.client.get("/health")
        return response.status_code == httpx.codes.OK
