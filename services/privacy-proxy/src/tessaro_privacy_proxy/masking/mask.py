"""The masking use case: find every personal value in a request and swap in placeholders."""

import asyncio
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from tessaro_privacy_proxy.masking.chunks import chunk
from tessaro_privacy_proxy.masking.directory import Directory
from tessaro_privacy_proxy.masking.entities import (
    ANALYZER_TYPES,
    EntityType,
    Source,
    Span,
    text_span,
)
from tessaro_privacy_proxy.masking.errors import UnsupportedContent
from tessaro_privacy_proxy.masking.jsontext import argument_strings, rewrite_arguments
from tessaro_privacy_proxy.masking.models import ChatMessage, ChatRequest, ToolCall
from tessaro_privacy_proxy.masking.patterns import find_patterns
from tessaro_privacy_proxy.masking.ports import Analyzer, MappingStore
from tessaro_privacy_proxy.masking.spans import resolve

ANALYZER_CONCURRENCY = 8
_LEGACY_FIELDS = ("functions", "function_call")
_ANALYZER_TYPES = frozenset(str(t) for t in ANALYZER_TYPES)


@dataclass(frozen=True)
class MaskResult:
    """The body to send upstream, and how many entities of each type were masked."""

    # Any: the outgoing JSON body keeps passthrough parameters of any shape.
    body: Mapping[str, Any]
    counts: Mapping[EntityType, int]


def _check_supported(request: ChatRequest) -> None:
    if any(field in request.passthrough() for field in _LEGACY_FIELDS):
        raise UnsupportedContent("legacy functions fields are not supported")
    for message in request.messages:
        if isinstance(message.content, tuple) and any(
            part.type != "text" or part.text is None for part in message.content
        ):
            raise UnsupportedContent("only text content parts are supported")


def _message_strings(message: ChatMessage) -> Iterator[str]:
    if isinstance(message.content, str):
        yield message.content
    elif message.content is not None:
        yield from (part.text for part in message.content if part.text is not None)
    for call in message.tool_calls or ():
        yield from argument_strings(call.function.arguments)


def _rewrite_call(call: ToolCall, convert: Callable[[str], str]) -> dict[str, Any]:
    return {
        "id": call.id,
        "type": call.type,
        "function": {
            "name": call.function.name,
            "arguments": rewrite_arguments(call.function.arguments, convert),
        },
    }


def _rewrite_message(message: ChatMessage, convert: Callable[[str], str]) -> dict[str, Any]:
    """The outgoing message: masked content and arguments, `name` dropped (AC-2)."""
    out: dict[str, Any] = {"role": message.role}
    if isinstance(message.content, str):
        out["content"] = convert(message.content)
    elif message.content is not None:
        out["content"] = [{"type": "text", "text": convert(p.text or "")} for p in message.content]
    else:
        out["content"] = None
    if message.tool_calls is not None:
        out["tool_calls"] = [_rewrite_call(c, convert) for c in message.tool_calls]
    if message.tool_call_id is not None:
        out["tool_call_id"] = message.tool_call_id
    return out


def _render(text: str, spans: Sequence[Span], placeholders: Mapping[str, str]) -> str:
    pieces: list[str] = []
    position = 0
    for span in spans:
        pieces.extend((text[position : span.start], placeholders[span.key]))
        position = span.end
    pieces.append(text[position:])
    return "".join(pieces)


@dataclass(frozen=True)
class Masker:
    """Directory, patterns and the analyzer find the spans; the store issues placeholders."""

    directory: Directory
    analyzer: Analyzer
    store: MappingStore
    score_threshold: float

    async def mask_request(self, request: ChatRequest, conversation_id: str) -> MaskResult:
        """The masked body. Raises before any upstream call when anything cannot be masked."""
        _check_supported(request)
        await self.store.touch(conversation_id)
        texts = sorted({t for m in request.messages for t in _message_strings(m) if t})
        limiter = asyncio.Semaphore(ANALYZER_CONCURRENCY)
        found = await asyncio.gather(*(self._detect(t, limiter) for t in texts))
        spans_by_text = dict(zip(texts, found, strict=True))
        placeholders = await self._allocate(conversation_id, spans_by_text)
        rendered = {t: _render(t, spans, placeholders) for t, spans in spans_by_text.items()}

        def convert(text: str) -> str:
            return rendered.get(text, text)

        body: dict[str, Any] = {
            **{k: v for k, v in request.passthrough().items() if k not in _LEGACY_FIELDS},
            "model": request.model,
            "messages": [_rewrite_message(m, convert) for m in request.messages],
        }
        if request.stream is not None:
            body["stream"] = request.stream
        counts = Counter(s.entity_type for spans in found for s in spans)
        return MaskResult(body=body, counts=dict(counts))

    async def _detect(self, text: str, limiter: asyncio.Semaphore) -> list[Span]:
        local = [*self.directory.find(text), *find_patterns(text)]
        remote = await asyncio.gather(*(self._analyze(text, o, c, limiter) for o, c in chunk(text)))
        return resolve([*local, *(s for spans in remote for s in spans)], text)

    async def _analyze(
        self, text: str, offset: int, piece: str, limiter: asyncio.Semaphore
    ) -> list[Span]:
        async with limiter:
            results = await self.analyzer.analyze(piece)
        return [
            text_span(
                offset + r.start, offset + r.end, EntityType(r.entity_type), Source.ANALYZER, text
            )
            for r in results
            if r.entity_type in _ANALYZER_TYPES
            and r.score >= self.score_threshold
            and 0 <= r.start < r.end <= len(piece)
        ]

    async def _allocate(
        self, conversation_id: str, spans_by_text: Mapping[str, Sequence[Span]]
    ) -> dict[str, str]:
        wanted: dict[str, Span] = {}
        for spans in spans_by_text.values():
            for span in spans:
                wanted.setdefault(span.key, span)
        issued = await asyncio.gather(
            *(
                self.store.placeholder_for(conversation_id, s.entity_type, s.key, s.original)
                for s in wanted.values()
            )
        )
        return dict(zip(wanted, issued, strict=True))
