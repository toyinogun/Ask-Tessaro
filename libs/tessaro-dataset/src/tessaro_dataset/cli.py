"""`tessaro-dataset`: validate the dataset, export it, or print a fresh stand in tuple.

Exit codes: 0 success, 1 invalid dataset (every problem printed), 2 bad usage.
"""

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import TextIO

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from tessaro_dataset.dataset import Dataset
from tessaro_dataset.dates import default_anchor, normalise_anchor
from tessaro_dataset.errors import DatasetError
from tessaro_dataset.exports import export_all, render_exports, render_tuples, stand_in_tuple
from tessaro_dataset.exports.openfga import OpenFgaExport
from tessaro_dataset.loader import DatasetPaths, load_dataset
from tessaro_dataset.registry import DEMO_TEAM

EXIT_OK = 0
EXIT_INVALID = 1
EXIT_USAGE = 2


class DatasetSettings(BaseSettings):
    """Optional env vars; command line flags win over them."""

    model_config = SettingsConfigDict(env_prefix="TESSARO_DATASET_", frozen=True, extra="ignore")

    anchor: datetime | None = None
    stand_in_minutes: int = Field(default=15, gt=0)


def _anchor(value: str) -> datetime:
    try:
        return normalise_anchor(datetime.fromisoformat(value))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not an ISO 8601 timestamp with an offset"
        ) from exc


def _positive(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{value!r} is not a whole number") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("must be above 0")
    return number


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tessaro-dataset", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, default=Path.cwd(), help="repo root")
    loading = argparse.ArgumentParser(add_help=False, parents=[common])
    loading.add_argument("--anchor", type=_anchor, help="ISO 8601 timestamp with offset")
    loading.add_argument("--stand-in-minutes", type=_positive, help="default 15")
    commands.add_parser("validate", parents=[loading], help="validate and print problems")
    export = commands.add_parser("export", parents=[loading], help="write one file per target")
    export.add_argument("--out", type=Path, required=True, help="output directory")
    export.add_argument("--include-demo-inputs", action="store_true", help="include the joiners")
    standin = commands.add_parser("standin", parents=[common], help="print a fresh stand in tuple")
    standin.add_argument("--minutes", type=_positive, required=True, help="window length")
    return parser


def _load(args: argparse.Namespace, settings: DatasetSettings) -> Dataset:
    minutes = args.stand_in_minutes or settings.stand_in_minutes
    anchor = args.anchor or (normalise_anchor(settings.anchor) if settings.anchor else None)
    return load_dataset(
        DatasetPaths.under(args.root), anchor=anchor, stand_in_duration=timedelta(minutes=minutes)
    )


def _warn(dataset: Dataset, err: TextIO) -> None:
    for warning in dataset.warnings:
        print(f"warning: {warning}", file=err)


def _run(args: argparse.Namespace, settings: DatasetSettings, out: TextIO, err: TextIO) -> int:
    if args.command == "standin":
        dataset = load_dataset(DatasetPaths.under(args.root))
        start = default_anchor()
        end = start + timedelta(minutes=args.minutes)
        row = stand_in_tuple(dataset.cast("stand_in").id, DEMO_TEAM, start, end)
        out.write(render_tuples(OpenFgaExport(tuples=(row,))))
        return EXIT_OK
    dataset = _load(args, settings)
    _warn(dataset, err)
    if args.command == "export":
        files = render_exports(export_all(dataset, include_demo_inputs=args.include_demo_inputs))
        args.out.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            (args.out / name).write_text(content, encoding="utf-8")
        print(f"wrote {len(files)} files to {args.out}", file=out)
        return EXIT_OK
    print(f"OK: {len(dataset.employees)} employees valid at {dataset.anchor.isoformat()}", file=out)
    return EXIT_OK


def main(
    argv: Sequence[str] | None = None, out: TextIO = sys.stdout, err: TextIO = sys.stderr
) -> int:
    """Entry point for the `tessaro-dataset` console script."""
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return EXIT_OK if exc.code == 0 else EXIT_USAGE
    try:
        settings = DatasetSettings()
    except ValidationError as exc:
        print(f"invalid TESSARO_DATASET_* setting: {exc}", file=err)
        return EXIT_USAGE
    try:
        return _run(args, settings, out, err)
    except DatasetError as exc:
        print(exc, file=err)
        return EXIT_INVALID
    except ValueError as exc:
        print(f"error: {exc}", file=err)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
