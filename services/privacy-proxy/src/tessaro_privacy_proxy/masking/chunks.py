"""Split long text for the analyzer only; local matching always sees the whole text (AC-17)."""

import re
from collections.abc import Iterator

MAX_CHUNK = 10_000
_LINE = re.compile(r"[^\n]*\n|[^\n]+")
_WORD = re.compile(r"\S+\s*|\s+")


def _pieces(text: str, limit: int) -> Iterator[tuple[int, str]]:
    """Lines, or for a line over the limit its words, or for a word over the limit hard cuts."""
    for line in _LINE.finditer(text):
        if len(line.group()) <= limit:
            yield line.start(), line.group()
            continue
        for word in _WORD.finditer(text, line.start(), line.end()):
            value = word.group()
            for i in range(0, len(value), limit):
                yield word.start() + i, value[i : i + limit]


def chunk(text: str, limit: int = MAX_CHUNK) -> list[tuple[int, str]]:
    """`(offset, piece)` pairs covering `text`, each at most `limit` characters.

    Pieces are packed greedily in order, so offsets stay contiguous and true.
    """
    if len(text) <= limit:
        return [(0, text)]
    chunks: list[tuple[int, str]] = []
    start, size = 0, 0
    for offset, piece in _pieces(text, limit):
        if size and size + len(piece) > limit:
            chunks.append((start, text[start : start + size]))
            start, size = offset, 0
        size += len(piece)
    if size:
        chunks.append((start, text[start : start + size]))
    return chunks
