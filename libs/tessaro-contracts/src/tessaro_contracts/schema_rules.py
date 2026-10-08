"""JSON Schema and model walkers behind the contract checks (spec 0003 AC-13).

The name walkers read only the keys inside each `properties` object, never schema
keywords such as `title` or `description`, and never literal values such as defaults.
"""

import types
import typing
from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from pydantic import AliasChoices, AliasPath, BaseModel

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
            for alias in (field.alias, field.validation_alias, field.serialization_alias):
                names.update(_alias_names(alias))
    return frozenset(names)


def _alias_names(alias: str | AliasPath | AliasChoices | None) -> Iterator[str]:
    """Every input name an alias accepts: each choice, and the first key of each path."""
    if isinstance(alias, str):
        yield alias
    elif isinstance(alias, AliasPath):
        if alias.path and isinstance(alias.path[0], str):
            yield alias.path[0]
    elif isinstance(alias, AliasChoices):
        for choice in alias.choices:
            yield from _alias_names(choice)


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


# Compatibility (spec 0003 AC-19): classify the difference between two MCP projections.

_TEXT_KEYWORDS: Final = frozenset({"title", "description"})
_SCHEMA_MAPS: Final = frozenset({"properties", "$defs", "definitions", "patternProperties"})
_BREAKING_META: Final = ("tessaro/scope", "tessaro/identity", "tessaro/owner", "tessaro/write")
_TEXT_META: Final = ("tessaro/authorization", "tessaro/never_returns")
VERSION_META: Final = "tessaro/version"


class Change(StrEnum):
    """How a projection changed against its snapshot."""

    NONE = "none"
    ADDITIVE = "additive"
    BREAKING = "breaking"


@dataclass(frozen=True, slots=True)
class Verdict:
    """The kind of change and the paths that made it so."""

    change: Change
    reasons: tuple[str, ...] = ()


def strip_text(node: object, schema_map: bool = False) -> object:
    """A copy of a schema without `title` and `description` keywords (property names kept)."""
    if isinstance(node, list):
        return [strip_text(item) for item in node]
    if not isinstance(node, dict):
        return node
    if schema_map:
        return {key: strip_text(value) for key, value in node.items()}
    return {
        key: value if key in _LITERAL_KEYWORDS else strip_text(value, key in _SCHEMA_MAPS)
        for key, value in node.items()
        if key not in _TEXT_KEYWORDS
    }


def _enum_values(node: dict[str, Any]) -> list[Any] | None:
    if "enum" in node:
        values: list[Any] = node["enum"]
        return values
    if "const" in node:
        return [node["const"]]
    return None


class _SchemaDiff:
    """Walks two text stripped schemas side by side, collecting breaking and additive paths."""

    def __init__(self, side: str) -> None:
        self.side = side
        self.breaking: list[str] = []
        self.additive: list[str] = []

    def compare(self, old: object, new: object, path: str) -> None:
        if isinstance(old, dict) and isinstance(new, dict):
            self._compare_objects(old, new, path)
        elif isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
            for index, (old_item, new_item) in enumerate(zip(old, new, strict=True)):
                self.compare(old_item, new_item, f"{path}[{index}]")
        elif old != new:
            self.breaking.append(path)

    def _compare_objects(self, old: dict[str, Any], new: dict[str, Any], path: str) -> None:
        self._compare_enums(old, new, path)
        added = set(new.get("properties", {})) - set(old.get("properties", {}))
        for key in sorted((old.keys() | new.keys()) - {"enum", "const"}):
            here = f"{path}.{key}"
            if key == "properties":
                self._compare_properties(old.get(key, {}), new.get(key, {}), new, here)
            elif key == "required":
                self._compare_required(old.get(key, []), new.get(key, []), added, here)
            elif key == "$defs":
                self._compare_defs(old.get(key, {}), new.get(key, {}), here)
            elif key not in old or key not in new:
                self.breaking.append(here)
            else:
                self.compare(old[key], new[key], here)

    def _compare_enums(self, old: dict[str, Any], new: dict[str, Any], path: str) -> None:
        old_values, new_values = _enum_values(old), _enum_values(new)
        if old_values == new_values:
            return
        widened = (
            self.side == "output"
            and old_values is not None
            and new_values is not None
            and all(value in new_values for value in old_values)
        )
        (self.additive if widened else self.breaking).append(f"{path}.enum")

    def _compare_properties(
        self, old: dict[str, Any], new: dict[str, Any], new_parent: dict[str, Any], path: str
    ) -> None:
        required = set(new_parent.get("required", []))
        for name in sorted(old.keys() | new.keys()):
            here = f"{path}.{name}"
            if name not in new:
                self.breaking.append(here)
            elif name not in old:
                allowed = self.side == "output" or name not in required
                (self.additive if allowed else self.breaking).append(here)
            else:
                self.compare(old[name], new[name], here)

    def _compare_required(self, old: list[str], new: list[str], added: set[str], path: str) -> None:
        dropped, gained = set(old) - set(new), set(new) - set(old)
        if dropped or (gained and (self.side == "input" or not gained <= added)):
            self.breaking.append(path)

    def _compare_defs(self, old: dict[str, Any], new: dict[str, Any], path: str) -> None:
        for name in sorted(old.keys() | new.keys()):
            here = f"{path}.{name}"
            if name not in new:
                self.breaking.append(here)
            elif name not in old:
                self.additive.append(here)
            else:
                self.compare(old[name], new[name], here)


def classify(old: JsonSchema, new: JsonSchema) -> Verdict:
    """Classify the change between two MCP projections, ignoring their versions."""
    old_meta, new_meta = old.get("_meta", {}), new.get("_meta", {})
    breaking = [f"_meta.{key}" for key in _BREAKING_META if old_meta.get(key) != new_meta.get(key)]
    additive = [f"_meta.{key}" for key in _TEXT_META if old_meta.get(key) != new_meta.get(key)]
    if old.get("name") != new.get("name"):
        breaking.append("name")
    if old.get("description") != new.get("description"):
        additive.append("description")
    for key, side in (("inputSchema", "input"), ("outputSchema", "output")):
        diff = _SchemaDiff(side)
        diff.compare(strip_text(old.get(key)), strip_text(new.get(key)), key)
        breaking.extend(diff.breaking)
        additive.extend(diff.additive)
        if not diff.breaking and not diff.additive and old.get(key) != new.get(key):
            additive.append(f"{key} (text)")
    if breaking:
        return Verdict(Change.BREAKING, tuple(breaking))
    if additive:
        return Verdict(Change.ADDITIVE, tuple(additive))
    return Verdict(Change.NONE)


def _version(projection: JsonSchema) -> tuple[int, int]:
    major, _, minor = str(projection.get("_meta", {}).get(VERSION_META, "0.0")).partition(".")
    return int(major), int(minor)


def compatibility_error(old: JsonSchema, new: JsonSchema) -> str | None:
    """Why `new` may not replace the snapshot `old`, or None when the version rule holds."""
    name = new.get("name", "?")
    verdict = classify(old, new)
    old_version, new_version = _version(old), _version(new)
    if verdict.change is Change.BREAKING:
        return (
            f"{name}: breaking change at {', '.join(verdict.reasons)}; "
            f"publish it as a new tool {name}_v2 instead"
        )
    if verdict.change is Change.NONE:
        if new_version != old_version:
            return f"{name}: version changed without a contract change"
        return None
    if new_version == old_version:
        return f"{name}: contract changed without a version change ({', '.join(verdict.reasons)})"
    if new_version[0] != old_version[0] or new_version[1] <= old_version[1]:
        return f"{name}: an additive change keeps the major version and raises the minor"
    return None
