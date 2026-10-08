"""Fixed names the dataset is checked against: groups, profiles, relations and the demo cast."""

from types import MappingProxyType
from typing import Final, Literal

DemoRole = Literal[
    "manager",
    "stand_in",
    "people_advisor",
    "second_advisor",
    "persona",
    "refused_colleague",
    "joiner",
    "second_joiner",
    "leaver",
    "mover",
    "it_approver",
    "sick_colleague",
]

DEMO_CAST: Final = MappingProxyType(
    {
        "manager": "TES-01001",
        "stand_in": "TES-01002",
        "persona": "TES-01003",
        "refused_colleague": "TES-01004",
        "sick_colleague": "TES-01006",
        "leaver": "TES-01007",
        "it_approver": "TES-01012",
        "people_advisor": "TES-01018",
        "second_advisor": "TES-01019",
        "mover": "TES-01023",
        "joiner": "TES-01042",
        "second_joiner": "TES-01043",
    }
)
"""Each demo role and the one employee ID that holds it (AC-15)."""

DEMO_TEAM: Final = "payments"
"""The team the demo plays out in: Maria's team, the stand in's team, both joiners' team."""

PERSONA_CLAIM_ID: Final = "EXP-0001"

DERIVED_GROUPS: Final = frozenset(
    {"staff", "managers", "people-advisors", "it-agents", "finance-team", "workplace-team"}
)
"""Authentik groups computed from employee data; `team-<id>` groups are added per team."""

EXTRA_GROUPS: Final = frozenset(
    {
        "eng",
        "prod-readonly",
        "it-admin",
        "hr-systems",
        "hr-admin",
        "finance-systems",
        "finance-admin",
        "facilities",
    }
)
"""Authentik groups a bundle may name beyond the derived ones."""

LAPTOP_PROFILES: Final = frozenset({"engineering-standard", "office-standard"})

ALLOWED_RELATIONS: Final = MappingProxyType(
    {
        ("team", "member"): frozenset({"user"}),
        ("team", "manager"): frozenset({"user"}),
        ("team", "stand_in"): frozenset({"user"}),
        ("team", "hr_advisor"): frozenset({"user"}),
        ("employee", "owner"): frozenset({"user"}),
        ("employee", "team"): frozenset({"team"}),
        ("lifecycle_case", "team"): frozenset({"team"}),
        ("lifecycle_case", "it_approver"): frozenset({"user"}),
    }
)
"""Directly assignable (object type, relation) pairs and their user types, from PRD 8.3."""

CONDITIONED_RELATIONS: Final = MappingProxyType({("team", "stand_in"): "within_window"})
"""Relations whose tuples must carry a condition, and its name."""


def known_groups(team_ids: frozenset[str]) -> frozenset[str]:
    """Every Authentik group name a bundle may use for these teams."""
    return DERIVED_GROUPS | EXTRA_GROUPS | {f"team-{team}" for team in team_ids}
