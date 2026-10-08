"""JSON Schema and model walkers behind the contract checks (spec 0003 AC-13).

The name walkers read only the keys inside each `properties` object, never schema
keywords such as `title` or `description`, and never literal values such as defaults.
"""

import types
import typing
from collections.abc import Iterator
from typing import Any, Final

from pydantic import BaseModel

_LITERAL_KEYWORDS: Final = frozenset({"default", "examples", "const", "enum"})
"""Keywords whose values are data, not schemas: never walked for property names."""

JsonSchema = dict[str, Any]
"""A JSON Schema document. Any: JSON values are arbitrarily nested."""


def property_names(schema: object) -> frozenset[str]:
    """Every property name anywhere in a JSON Schema, including under `$defs`."""
    return frozenset(_property_names(schema))


def _property_names(node: object) -> Iterator[str]:
    if isinstance(node, list):
        for item in node:
            yield from _property_names(item)
        return
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if key in _LITERAL_KEYWORDS:
            continue
        if key == "properties" and isinstance(value, dict):
            yield from value.keys()
            for sub_schema in value.values():
                yield from _property_names(sub_schema)
        else:
            yield from _property_names(value)


def model_schemas(model: type[BaseModel]) -> tuple[JsonSchema, JsonSchema]:
    """The model's JSON Schema in validation and serialization mode (aliases can differ)."""
    return (
        model.model_json_schema(mode="validation"),
        model.model_json_schema(mode="serialization"),
    )


def all_names(model: type[BaseModel]) -> frozenset[str]:
    """Every field name and alias of the model and every model nested in it."""
    names: set[str] = set()
    for schema in model_schemas(model):
        names |= property_names(schema)
    for nested in nested_models(model):
        for field_name, field in nested.model_fields.items():
            names.add(field_name)
            names.update(
                alias
                for alias in (field.alias, field.validation_alias, field.serialization_alias)
                if isinstance(alias, str)
            )
    return frozenset(names)


def nested_models(model: type[BaseModel]) -> tuple[type[BaseModel], ...]:
    """The model itself and every model reachable through its field annotations."""
    seen: dict[type[BaseModel], None] = {}
    pending = [model]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen[current] = None
        for field in current.model_fields.values():
            pending.extend(_models_in(field.annotation))
    return tuple(seen)


def _models_in(annotation: object) -> Iterator[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        yield annotation
        return
    if isinstance(annotation, typing.TypeAliasType):
        yield from _models_in(annotation.__value__)
        return
    origin = typing.get_origin(annotation)
    if origin is typing.Annotated:
        yield from _models_in(typing.get_args(annotation)[0])
        return
    if origin is not None or isinstance(annotation, types.UnionType):
        for arg in typing.get_args(annotation):
            yield from _models_in(arg)


def is_frozen_and_closed(model: type[BaseModel]) -> bool:
    """True when the model is frozen and forbids extra fields."""
    config = model.model_config
    return config.get("frozen") is True and config.get("extra") == "forbid"


def normalized_name(name: str) -> str:
    """Lowercase with underscores removed, for the identity field check."""
    return name.lower().replace("_", "")
