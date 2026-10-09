"""Split long text for the analyzer only; local matching always sees the whole text (AC-17)."""

import re
from collections.abc import Iterator
from itertools import pairwise

MAX_CHUNK = 10_000
OVERLAP = 300
_LINE = re.compile(r"[^\n]*\n|[^\n]+")
_WORD = re.compile(r"\S+\s*|\s+")
_SPACE = re.compile(r"\s")


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


def _packed(text: str, limit: int) -> list[tuple[int, int]]:
    """`(start, end)` ranges packed greedily in order, contiguous and each at most `limit`."""
    ranges: list[tuple[int, int]] = []
    start, size = 0, 0
    for offset, piece in _pieces(text, limit):
        if size and size + len(piece) > limit:
            ranges.append((start, start + size))
            start, size = offset, 0
        size += len(piece)
    if size:
        ranges.append((start, start + size))
    return ranges


def _reach_back(text: str, floor: int, start: int, overlap: int) -> int:
    """`start` moved back by up to `overlap` but not before `floor`, after a space if any."""
    earliest = max(floor, start - overlap)
    space = _SPACE.search(text, earliest, start)
    return space.end() if space else earliest


def chunk(text: str, limit: int = MAX_CHUNK, overlap: int = OVERLAP) -> list[tuple[int, str]]:
    """`(offset, piece)` pairs covering `text`, each at most `limit` characters.

    Each piece after the first also repeats up to `overlap` characters before it, so a
    name or number cut by one boundary is whole in the next piece. Offsets stay true;
    the overlap resolution drops the duplicate hits.
    """
    if overlap * 2 >= limit:
        raise ValueError("overlap must be under half the chunk limit")
    if len(text) <= limit:
        return [(0, text)]
    ranges = _packed(text, limit - overlap)
    starts = [0, *(_reach_back(text, p[0] + 1, r[0], overlap) for p, r in pairwise(ranges))]
    return [(s, text[s:end]) for s, (_, end) in zip(starts, ranges, strict=True)]
