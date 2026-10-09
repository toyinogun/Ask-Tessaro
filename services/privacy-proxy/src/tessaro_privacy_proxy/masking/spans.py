"""Overlap resolution: one span per character, never nested, never half masked (AC-15)."""

from collections.abc import Iterable

from tessaro_privacy_proxy.masking.entities import Source, Span, text_span

_APOSTROPHES = ("'", "\u2019")


def _priority(span: Span) -> tuple[int, int, int]:
    return (span.source, -span.length, span.start)


def _trim_possessive(span: Span, text: str) -> Span | None:
    """An analyzer span without a trailing `'s` (also with U+2019); None if nothing is left.

    The analyzer often includes the possessive in a name, which would stop the directory
    match from containing it. Directory and pattern spans are never trimmed.
    """
    if span.source is not Source.ANALYZER or span.length < 2:
        return span
    tail = text[span.end - 2 : span.end]
    if tail[0] not in _APOSTROPHES or tail[1] not in ("s", "S"):
        return span
    if span.length == 2:
        return None
    return text_span(span.start, span.end - 2, span.entity_type, span.source, text)


def _widen(winner: Span, others: Iterable[Span], text: str) -> Span:
    """One span over the winner and every overlapping span, with the winner's type.

    Only a partly overlapping span is merged, so the result is always wider than the
    winner, and a wider span is keyed by its own text even when the winner was keyed by
    an employee: the extra words mean it may be someone else ("Jan Bakker" is not the
    employee whose surname is Bakker). An exact match never gets here; it is contained.
    """
    group = (winner, *others)
    start = min(s.start for s in group)
    end = max(s.end for s in group)
    return text_span(start, end, winner.entity_type, winner.source, text)


def resolve(spans: Iterable[Span], text: str) -> list[Span]:
    """Pick the winners: directory, then pattern, then analyzer; then longer; then earlier.

    Analyzer possessives are trimmed first. A span inside an accepted span is dropped; a
    span that only partly overlaps accepted spans is merged with them into one wider span
    with the strongest one's type, keyed by its own text (see `_widen`).
    Returns the spans sorted by start.
    """
    trimmed = (_trim_possessive(span, text) for span in spans)
    accepted: list[Span] = []
    for candidate in sorted((s for s in trimmed if s is not None), key=_priority):
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
