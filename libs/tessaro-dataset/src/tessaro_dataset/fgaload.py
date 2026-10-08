"""`python -m tessaro_dataset.fgaload`: the Python half of `just authz-load` (spec 0004 AC-11).

`ids` reads the JSON `fga store create` printed and prints `<store id> <model id>`.
`env` checks both outputs again, including that `fga tuple write` failed no tuple (the CLI
exits 0 even when some tuples fail), and only then sets `OPENFGA_STORE_ID` and
`OPENFGA_MODEL_ID` in `.env`. Any problem exits 1 and leaves `.env` untouched.
"""

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

STORE_VAR: Final = "OPENFGA_STORE_ID"
MODEL_VAR: Final = "OPENFGA_MODEL_ID"


class FgaLoadError(Exception):
    """The fga CLI output was not a clean store create or tuple write."""


@dataclass(frozen=True)
class StoreCreated:
    """The IDs `fga store create --model` returned."""

    store_id: str
    model_id: str


def _json_object(text: str, what: str) -> dict[str, object]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FgaLoadError(f"{what}: not JSON ({exc.msg})") from exc
    if not isinstance(value, dict):
        raise FgaLoadError(f"{what}: expected a JSON object")
    return value


def _string_at(document: dict[str, object], section: str, key: str, what: str) -> str:
    inner = document.get(section)
    value = inner.get(key) if isinstance(inner, dict) else None
    if not isinstance(value, str) or not value:
        raise FgaLoadError(f"{what}: no {section}.{key}")
    return value


def parse_store_create(text: str) -> StoreCreated:
    """The store and model IDs from `fga store create --model` JSON output."""
    document = _json_object(text, "fga store create")
    return StoreCreated(
        store_id=_string_at(document, "store", "id", "fga store create"),
        model_id=_string_at(document, "model", "authorization_model_id", "fga store create"),
    )


def check_tuple_write(text: str) -> int:
    """The number of tuples written; raises when any tuple failed or the output is unclear."""
    document = _json_object(text, "fga tuple write")
    failed = document.get("failed_count")
    written = document.get("successful_count")
    if not isinstance(failed, int) or not isinstance(written, int):
        raise FgaLoadError("fga tuple write: no failed_count or successful_count")
    if failed:
        raise FgaLoadError(f"fga tuple write: {failed} tuples failed")
    return written


def set_env(text: str, values: Mapping[str, str]) -> str:
    """New `.env` text with each variable set once: first line replaced, duplicates dropped."""
    pending = dict(values)
    seen: set[str] = set()
    lines: list[str] = []
    for line in text.splitlines():
        name = line.partition("=")[0].strip()
        if "=" not in line or line.lstrip().startswith("#") or name not in values:
            lines.append(line)
        elif name not in seen:
            seen.add(name)
            lines.append(f"{name}={pending.pop(name)}")
    lines.extend(f"{name}={value}" for name, value in pending.items())
    return "\n".join(lines) + "\n"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FgaLoadError(f"cannot read {path}: {exc.strerror}") from exc


def _ids(args: argparse.Namespace) -> None:
    created = parse_store_create(_read(args.store_json))
    sys.stdout.write(f"{created.store_id} {created.model_id}\n")


def _env(args: argparse.Namespace) -> None:
    created = parse_store_create(_read(args.store_json))
    written = check_tuple_write(_read(args.write_json))
    env_file: Path = args.env_file
    updated = set_env(_read(env_file), {STORE_VAR: created.store_id, MODEL_VAR: created.model_id})
    env_file.write_text(updated, encoding="utf-8")
    sys.stdout.write(
        f"{env_file}: {written} tuples loaded; set {STORE_VAR}={created.store_id} "
        f"and {MODEL_VAR}={created.model_id}\n"
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for `just authz-load`."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    commands = parser.add_subparsers(dest="command", required=True)
    ids = commands.add_parser("ids", help="print the store and model IDs")
    ids.add_argument("--store-json", type=Path, required=True)
    ids.set_defaults(run=_ids)
    env = commands.add_parser("env", help="check the load, then set both IDs in .env")
    env.add_argument("--env-file", type=Path, default=Path(".env"))
    env.add_argument("--store-json", type=Path, required=True)
    env.add_argument("--write-json", type=Path, required=True)
    env.set_defaults(run=_env)
    args = parser.parse_args(argv)
    try:
        args.run(args)
    except FgaLoadError as exc:
        sys.stderr.write(f"authz-load: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
