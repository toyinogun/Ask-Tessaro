"""Overlap resolution: one span per character, never nested, never half masked (AC-15)."""

from collections.abc import Iterable
from dataclasses import replace

from tessaro_privacy_proxy.masking.entities import Span, text_span


def _priority(span: Span) -> tuple[int, int, int]:
    return (span.source, -span.length, span.start)


def _widen(winner: Span, others: Iterable[Span], text: str) -> Span:
    """The winner stretched over every overlapping span, keeping the winner's type.

    A winner keyed by an employee keeps its key and original; a winner keyed by its text
    is keyed again by the wider text, since the key is that text.
    """
    group = (winner, *others)
    start = min(s.start for s in group)
    end = max(s.end for s in group)
    if "|emp:" in winner.key:
        return replace(winner, start=start, end=end)
    return text_span(start, end, winner.entity_type, winner.source, text)


def resolve(spans: Iterable[Span], text: str) -> list[Span]:
    """Pick the winners: directory, then pattern, then analyzer; then longer; then earlier.

    A span inside an accepted span is dropped; a span that only partly overlaps accepted
    spans is merged with them into one wider span with the strongest one's type and key.
    Returns the spans sorted by start.
    """
    accepted: list[Span] = []
    for candidate in sorted(spans, key=_priority):
        touching = [a for a in accepted if a.overlaps(candidate)]
        if not touching:
            accepted = [*accepted, candidate]
            continue
        if any(a.contains(candidate) for a in touching):
            continue
        winner = min(touching, key=_priority)
        merged = _widen(winner, [*touching, candidate], text)
        # Accepted spans never overlap each other, so the merge cannot reach any other span.
        accepted = [*(a for a in accepted if a not in touching), merged]
    return sorted(accepted, key=lambda s: s.start)
