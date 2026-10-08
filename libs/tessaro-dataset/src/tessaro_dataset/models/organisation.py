"""Offices, spaces, teams, Zulip channels and access bundles."""

from typing import Literal

from pydantic import Field

from tessaro_dataset.models.common import Count, EmployeeId, Record, Slug, Text

TicketQueue = Literal["it", "people", "finance", "workplace"]


class Office(Record):
    """A Tessaro office; employees have a home office and spaces sit in one."""

    id: Slug
    name: Text
    street: Text
    postcode: Text
    city: Text
    timezone: Text


class Space(Record):
    """A bookable desk or meeting room."""

    id: Slug
    office_id: Slug
    kind: Literal["desk", "room"]
    name: Text
    capacity: Count = Field(ge=1)


class Team(Record):
    """One of the five teams, its manager and its People advisors."""

    id: Slug
    name: Text
    manager_id: EmployeeId
    hr_advisor_ids: tuple[EmployeeId, ...] = Field(min_length=1)
    ticket_queue: TicketQueue | None = None


class Channel(Record):
    """A Zulip channel; team members come from bundles, others are listed here."""

    name: Slug
    description: Text
    extra_member_ids: tuple[EmployeeId, ...] = ()


class ElevatedGroup(Record):
    """An Authentik group in a bundle that needs IT approval."""

    authentik_group: Slug


class AccessBundle(Record):
    """A team's access bundle (PRD 9.5 shape)."""

    team: Slug
    authentik_groups: tuple[Slug, ...]
    zulip_channels: tuple[Slug, ...]
    elevated: tuple[ElevatedGroup, ...] = ()
    laptop_profile: Slug
    default_office: Slug
