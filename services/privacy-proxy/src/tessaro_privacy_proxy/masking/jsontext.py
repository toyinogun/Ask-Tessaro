"""Walk the strings inside a tool call's JSON arguments, keys and non strings untouched."""

import json
from collections.abc import Callable, Iterator
from typing import Any

# Any: tool call arguments are arbitrary JSON written by the model or the agent.
JsonValue = Any


def _leaves(value: JsonValue) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _leaves(item)
    elif isinstance(value, list):
        for item in value:
            yield from _leaves(item)


def _rewrite(value: JsonValue, convert: Callable[[str], str]) -> JsonValue:
    if isinstance(value, str):
        return convert(value)
    if isinstance(value, dict):
        return {key: _rewrite(item, convert) for key, item in value.items()}
    if isinstance(value, list):
        return [_rewrite(item, convert) for item in value]
    return value


def _parse(arguments: str) -> tuple[bool, JsonValue]:
    try:
        return True, json.loads(arguments)
    except ValueError:
        return False, None


def argument_strings(arguments: str) -> list[str]:
    """The string values inside `arguments`, or the raw text when it is not valid JSON."""
    valid, parsed = _parse(arguments)
    return list(_leaves(parsed)) if valid else [arguments]


def rewrite_arguments(arguments: str, convert: Callable[[str], str]) -> str:
    """`arguments` with every string value converted, rebuilt with `ensure_ascii=False`.

    Arguments that are not valid JSON are converted as raw text.
    """
    valid, parsed = _parse(arguments)
    if not valid:
        return convert(arguments)
    return json.dumps(_rewrite(parsed, convert), ensure_ascii=False)
