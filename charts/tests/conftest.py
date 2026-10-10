"""Shared helpers for the chart tests: render a chart with `helm template` and parse the result."""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]

# Rendered Kubernetes objects are arbitrary nested mappings, so Any is the honest type here.
Manifest = dict[str, Any]
Render = Callable[..., list[Manifest]]


def _render(
    chart: str, *value_files: Path, release: str = "test", values: dict[str, Any] | None = None
) -> list[Manifest]:
    args = ["helm", "template", release, str(REPO_ROOT / "charts" / chart)]
    for path in value_files:
        args += ["--values", str(path)]
    with tempfile.NamedTemporaryFile("w", suffix=".yaml") as extra:
        if values is not None:
            yaml.safe_dump(values, extra)
            extra.flush()
            args += ["--values", extra.name]
        # Fixed args: helm, a chart under charts/ and value files this suite controls.
        result = subprocess.run(args, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        # ValueError, not a custom class: test modules cannot import from conftest under importlib.
        raise ValueError(f"helm template failed: {result.stderr}")
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


@pytest.fixture(scope="session")
def render() -> Render:
    """Render a chart under charts/ with value files, then an optional inline values dict.

    Raises ValueError with helm's message when the chart refuses the values.
    """
    return _render
