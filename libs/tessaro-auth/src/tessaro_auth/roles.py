"""The one fixed mapping from Authentik group names to token roles."""

from collections.abc import Iterable
from types import MappingProxyType
from typing import Final

from tessaro_auth.claims import Role
from tessaro_contracts.scopes import Scope

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


_EMPLOYEE_SCOPES: Final = frozenset(
    {
        Scope.IT_READ,
        Scope.HR_READ,
        Scope.FINANCE_READ,
        Scope.WORKPLACE_READ,
        Scope.KB_READ,
        Scope.QUEUE_HANDOFF,
        Scope.WORKFLOW_READ,
    }
)

ROLE_SCOPES: Final = MappingProxyType(
    {
        Role.EMPLOYEE: _EMPLOYEE_SCOPES,
        Role.MANAGER: _EMPLOYEE_SCOPES | {Scope.TEAM_READ},
        Role.IT_SERVICE_DESK: frozenset({Scope.IT_READ_ANY, Scope.WORKFLOW_READ_ANY}),
        Role.PEOPLE_ADVISOR: frozenset({Scope.HR_READ_ANY, Scope.WORKFLOW_READ_ANY}),
        Role.WORKFLOW_WORKER: frozenset(
            {Scope.IDENTITY_WRITE, Scope.IT_WRITE, Scope.WORKPLACE_WRITE, Scope.HR_READ_ANY}
        ),
    }
)
"""PRD 8.2, Manager flattened. The only source of `policy/role_scopes.json` (spec 0005)."""
