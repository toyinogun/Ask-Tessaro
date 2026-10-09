"""An in memory analyzer for tests and the CI leak scan: finds the strings it is told to."""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from tessaro_privacy_proxy.masking.errors import AnalyzerUnavailable
from tessaro_privacy_proxy.masking.ports import AnalyzerResult


@dataclass(frozen=True)
class FakeAnalyzer:
    """Reports every case insensitive occurrence of each known value with its type.

    With `down=True` every call raises `AnalyzerUnavailable`, as a dead analyzer would.
    """

    known: tuple[tuple[str, str], ...] = ()
    score: float = 0.85
    down: bool = False

    @classmethod
    def finding(cls, values: Iterable[tuple[str, str]], score: float = 0.85) -> "FakeAnalyzer":
        """A fake that finds each `(entity_type, text)` pair."""
        return cls(known=tuple(values), score=score)

    async def analyze(self, text: str) -> Sequence[AnalyzerResult]:
        """Every occurrence of every known value in `text`."""
        if self.down:
            raise AnalyzerUnavailable("fake analyzer is down")
        return [
            AnalyzerResult(entity_type, m.start(), m.end(), self.score)
            for entity_type, value in self.known
            for m in re.finditer(re.escape(value), text, re.IGNORECASE)
        ]
