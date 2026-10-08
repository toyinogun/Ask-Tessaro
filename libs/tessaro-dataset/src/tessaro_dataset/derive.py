"""Values computed from the data, never written by hand: emails, IBANs, groups, reports to."""

import re
import unicodedata

from tessaro_dataset.dataset import Dataset
from tessaro_dataset.models import Employee

EMAIL_DOMAIN = "tessaro.example"
BANK_CODE = "XTSR"
COUNTRY = "NL"


def _slug_part(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", ascii_text.lower())


def display_name(employee: Employee) -> str:
    """First name, tussenvoegsel and last name, as shown in Zulip and the directory."""
    parts = (employee.first_name, employee.tussenvoegsel, employee.last_name)
    return " ".join(p for p in parts if p)


def full_last_name(employee: Employee) -> str:
    """The last name with its tussenvoegsel (`de Wit`)."""
    return (
        f"{employee.tussenvoegsel} {employee.last_name}"
        if employee.tussenvoegsel
        else (employee.last_name)
    )


def email(employee: Employee) -> str:
    """`first.lastname@tessaro.example`, the tussenvoegsel joined in (`daan.dewit`)."""
    if employee.email_override:
        return employee.email_override
    last = _slug_part((employee.tussenvoegsel or "") + employee.last_name)
    return f"{_slug_part(employee.first_name)}.{last}@{EMAIL_DOMAIN}"


def _iban_digits(text: str) -> int:
    return int("".join(str(int(ch, 36)) for ch in text))


def iban(account_number: str) -> str:
    """A Dutch style IBAN on the made up bank code, with a valid mod 97 checksum."""
    check = 98 - _iban_digits(f"{BANK_CODE}{account_number}{COUNTRY}00") % 97
    return f"{COUNTRY}{check:02d}{BANK_CODE}{account_number}"


def iban_is_valid(value: str) -> bool:
    """Whether an IBAN passes the ISO 13616 mod 97 check."""
    return _iban_digits(value[4:] + value[:4]) % 97 == 1


def reports_to(dataset: Dataset, employee: Employee) -> str | None:
    """Members report to their team manager, managers to the CEO, the CEO to no one."""
    if employee.is_ceo or employee.team_id is None:
        return None
    team = dataset.teams_by_id[employee.team_id]
    if team.manager_id == employee.id:
        return dataset.ceo.id
    return team.manager_id


def authentik_groups(dataset: Dataset, employee: Employee) -> tuple[str, ...]:
    """The groups a person belongs to in the seed (AC-9), sorted."""
    groups = {"staff"}
    if employee.it_agent:
        groups.add("it-agents")
    if any(employee.id in t.hr_advisor_ids for t in dataset.teams):
        groups.add("people-advisors")
    if any(employee.id == t.manager_id for t in dataset.teams):
        groups.add("managers")
    team_id = employee.team_id
    if team_id is not None:
        groups.add(f"team-{team_id}")
        if team_id in ("finance", "workplace"):
            groups.add(f"{team_id}-team")
        bundle = dataset.bundles_by_team.get(team_id)
        if bundle is not None:
            elevated = {e.authentik_group for e in bundle.elevated}
            groups.update(g for g in bundle.authentik_groups if g not in elevated)
    return tuple(sorted(groups))


def zulip_channels(dataset: Dataset, employee: Employee) -> tuple[str, ...]:
    """The bundle's channels for the person's team plus channels naming them as extras."""
    names: set[str] = set()
    bundle = dataset.bundles_by_team.get(employee.team_id or "")
    if bundle is not None:
        names.update(bundle.zulip_channels)
    names.update(c.name for c in dataset.channels if employee.id in c.extra_member_ids)
    return tuple(sorted(names))


def directory_forms(employee: Employee) -> tuple[str, ...]:
    """Every way the person may be written in a message, for the privacy proxy (sorted)."""
    forms = {
        display_name(employee),
        employee.first_name,
        employee.last_name,
        full_last_name(employee),
        f"{employee.first_name} {employee.last_name}",
        email(employee),
        employee.id,
        f"@**{display_name(employee)}**",
    }
    return tuple(sorted(forms))
