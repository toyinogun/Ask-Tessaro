"""The privacy proxy's directory: every way each person may be written, joiners included."""

from tessaro_dataset.dataset import Dataset
from tessaro_dataset.derive import directory_forms, display_name, email, full_last_name
from tessaro_dataset.exports.base import ExportRecord


class DirectoryEntry(ExportRecord):
    """One person and the name forms the proxy must recognise."""

    employee_id: str
    display_name: str
    first_name: str
    last_name: str
    last_name_with_tussenvoegsel: str
    email: str
    zulip_handle: str
    forms: tuple[str, ...]


class DirectoryExport(ExportRecord):
    """Every person, sorted by employee ID."""

    entries: tuple[DirectoryEntry, ...]


def export_directory(dataset: Dataset, include_demo_inputs: bool = False) -> DirectoryExport:
    """Always includes the demo input joiners: the proxy must know them before they exist."""
    return DirectoryExport(
        entries=tuple(
            DirectoryEntry(
                employee_id=e.id,
                display_name=display_name(e),
                first_name=e.first_name,
                last_name=e.last_name,
                last_name_with_tussenvoegsel=full_last_name(e),
                email=email(e),
                zulip_handle=display_name(e),
                forms=directory_forms(e),
            )
            for e in sorted(dataset.employees, key=lambda e: e.id)
        )
    )
