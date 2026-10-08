"""One exporter per target system, plus `export_all` and the file renderer."""

import json
from collections.abc import Callable, Mapping
from types import MappingProxyType

import yaml

from tessaro_dataset.dataset import Dataset
from tessaro_dataset.exports.authentik import export_authentik
from tessaro_dataset.exports.base import ExportRecord
from tessaro_dataset.exports.bookstack import export_bookstack
from tessaro_dataset.exports.demo_actions import export_demo_actions
from tessaro_dataset.exports.directory import export_directory
from tessaro_dataset.exports.erpnext import export_erpnext
from tessaro_dataset.exports.frappe_hr import export_frappe_hr
from tessaro_dataset.exports.openfga import OpenFgaExport, export_openfga, stand_in_tuple
from tessaro_dataset.exports.seatsurfing import export_seatsurfing
from tessaro_dataset.exports.snipeit import export_snipeit
from tessaro_dataset.exports.zammad import export_zammad
from tessaro_dataset.exports.zulip import export_zulip

Exporter = Callable[[Dataset, bool], ExportRecord]

EXPORTERS: Mapping[str, Exporter] = MappingProxyType(
    {
        "authentik": export_authentik,
        "bookstack": export_bookstack,
        "demo_actions": export_demo_actions,
        "directory": export_directory,
        "erpnext": export_erpnext,
        "frappe_hr": export_frappe_hr,
        "openfga": export_openfga,
        "seatsurfing": export_seatsurfing,
        "snipeit": export_snipeit,
        "zammad": export_zammad,
        "zulip": export_zulip,
    }
)
OPENFGA_FILE = "openfga.tuples.yaml"


def export_all(dataset: Dataset, include_demo_inputs: bool = False) -> dict[str, ExportRecord]:
    """Every target's export, keyed by target name."""
    return {name: run(dataset, include_demo_inputs) for name, run in EXPORTERS.items()}


def render_tuples(export: OpenFgaExport) -> str:
    """Tuples as an fga CLI tuple file (YAML)."""
    rows = [t.model_dump(mode="json", exclude_none=True) for t in export.tuples]
    return yaml.safe_dump(rows, sort_keys=True, allow_unicode=True)


def render_exports(exports: Mapping[str, ExportRecord]) -> dict[str, str]:
    """File name to file content; JSON with sorted keys so the output is byte stable."""
    files: dict[str, str] = {}
    for name, export in sorted(exports.items()):
        if isinstance(export, OpenFgaExport):
            files[OPENFGA_FILE] = render_tuples(export)
        else:
            payload = export.model_dump(mode="json")
            files[f"{name}.json"] = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    return files


__all__ = [
    "EXPORTERS",
    "OPENFGA_FILE",
    "export_all",
    "render_exports",
    "render_tuples",
    "stand_in_tuple",
]
