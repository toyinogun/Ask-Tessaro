"""The restore use case: put the real values back into the model's answer (FR-P5, AC-7)."""

import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from tessaro_privacy_proxy.masking.jsontext import argument_strings, rewrite_arguments
from tessaro_privacy_proxy.masking.ports import MappingStore

PLACEHOLDER = re.compile(r"<[A-Z_]+_\d+>")
_DROPPED_MESSAGE_FIELDS = frozenset({"reasoning_content"})
_DROPPED_CHOICE_FIELDS = frozenset({"logprobs"})
_TEXT_FIELDS = ("content", "refusal")


@dataclass(frozen=True)
class RestoreResult:
    """The restored response, and placeholders the conversation never issued (for the log)."""

    # Any: the upstream response is open ended JSON; only known fields are rewritten.
    body: Mapping[str, Any]
    unknown: tuple[str, ...]


def _messages(body: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    choices = body.get("choices")
    for choice in choices if isinstance(choices, list) else ():
        message = choice.get("message") if isinstance(choice, dict) else None
        if isinstance(message, dict):
            yield message


def _tool_calls(message: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    calls = message.get("tool_calls")
    for call in calls if isinstance(calls, list) else ():
        function = call.get("function") if isinstance(call, dict) else None
        if isinstance(function, dict) and isinstance(function.get("arguments"), str):
            yield function


def _strings(body: Mapping[str, Any]) -> Iterator[str]:
    for message in _messages(body):
        for field in _TEXT_FIELDS:
            value = message.get(field)
            if isinstance(value, str):
                yield value
        for function in _tool_calls(message):
            yield from argument_strings(function["arguments"])


def _rewrite_function(function: Mapping[str, Any], convert: Callable[[str], str]) -> Any:
    if not isinstance(function.get("arguments"), str):
        return function
    return {**function, "arguments": rewrite_arguments(function["arguments"], convert)}


def _rewrite_call(call: Any, convert: Callable[[str], str]) -> Any:
    if not isinstance(call, dict) or not isinstance(call.get("function"), dict):
        return call
    return {**call, "function": _rewrite_function(call["function"], convert)}


def _rewrite_message(message: Mapping[str, Any], convert: Callable[[str], str]) -> Any:
    out = {k: v for k, v in message.items() if k not in _DROPPED_MESSAGE_FIELDS}
    for field in _TEXT_FIELDS:
        if isinstance(out.get(field), str):
            out[field] = convert(out[field])
    if isinstance(out.get("tool_calls"), list):
        out["tool_calls"] = [_rewrite_call(c, convert) for c in out["tool_calls"]]
    return out


def _rewrite_choice(choice: Any, convert: Callable[[str], str]) -> Any:
    if not isinstance(choice, dict):
        return choice
    out = {k: v for k, v in choice.items() if k not in _DROPPED_CHOICE_FIELDS}
    if isinstance(out.get("message"), dict):
        out["message"] = _rewrite_message(out["message"], convert)
    return out


async def restore_response(
    body: Mapping[str, Any], conversation_id: str, store: MappingStore
) -> RestoreResult:
    """`body` with every issued placeholder replaced in one pass, so nothing expands twice."""
    seen = sorted({p for text in _strings(body) for p in PLACEHOLDER.findall(text)})
    originals = await store.originals(conversation_id, seen) if seen else {}

    def convert(text: str) -> str:
        return PLACEHOLDER.sub(lambda m: originals.get(m.group(), m.group()), text)

    choices = body.get("choices")
    restored = dict(body)
    if isinstance(choices, list):
        restored["choices"] = [_rewrite_choice(c, convert) for c in choices]
    unknown = tuple(p for p in seen if p not in originals)
    return RestoreResult(body=restored, unknown=unknown)
