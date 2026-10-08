"""The one fixed mapping from Authentik group names to token roles."""

from collections.abc import Iterable
from types import MappingProxyType
from typing import Final

from tessaro_auth.claims import Role

GROUP_TO_ROLE: Final = MappingProxyType(
    {
        "staff": Role.EMPLOYEE,
        "managers": Role.MANAGER,
        "it-agents": Role.IT_SERVICE_DESK,
        "people-advisors": Role.PEOPLE_ADVISOR,
    }
)
"""Exact, case sensitive group names. No group ever yields `workflow_worker`."""


def roles_from_groups(groups: Iterable[str]) -> tuple[Role, ...]:
    """Map Authentik groups to roles, ignoring unknown groups; deduplicated and sorted."""
    return tuple(sorted({GROUP_TO_ROLE[g] for g in groups if g in GROUP_TO_ROLE}))
