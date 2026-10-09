"""The two dependencies the masking use cases talk to, as protocols (adapters live outside)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from tessaro_privacy_proxy.masking.entities import EntityType


@dataclass(frozen=True)
class AnalyzerResult:
    """One analyzer hit: Python string offsets into the text that was analyzed."""

    entity_type: str
    start: int
    end: int
    score: float


class Analyzer(Protocol):
    """Finds personal data in one text. Raises `AnalyzerUnavailable` on any failure."""

    async def analyze(self, text: str) -> Sequence[AnalyzerResult]:
        """Hits for the analyzer types at or above the configured score threshold."""
        ...


class MappingStore(Protocol):
    """A conversation's placeholder mapping. Raises `MappingStoreUnavailable` on any failure."""

    async def touch(self, conversation_id: str) -> None:
        """Refresh the conversation's expiry; fail when only some of its keys exist."""
        ...

    async def placeholder_for(
        self, conversation_id: str, entity_type: EntityType, key: str, original: str
    ) -> str:
        """The conversation's placeholder for `key`, issuing the next one if it is new."""
        ...

    async def originals(
        self, conversation_id: str, placeholders: Sequence[str]
    ) -> Mapping[str, str]:
        """The original text of each placeholder the conversation issued; others are absent."""
        ...
