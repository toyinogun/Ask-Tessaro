"""Minting rules: roles, refusals in order, worker tokens and signer kinds (AC-2 to AC-5)."""

from dataclasses import replace
from datetime import UTC, datetime

import jwt
import pytest

from tessaro_auth.claims import Role
from tessaro_auth.issue import (
    DirectoryIdentity,
    MintReason,
    MintRefused,
    issue_human_token,
    issue_worker_token,
)
from tessaro_auth.keys import Signer
from tessaro_auth.roles import roles_from_groups

NOW = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)
RID = "0123456789abcdef0123456789abcdef"


def _claims(token: str) -> dict[str, object]:
    decoded: dict[str, object] = jwt.decode(token, options={"verify_signature": False})
    return decoded


@pytest.mark.parametrize(
    ("groups", "expected"),
    [
        (("staff",), (Role.EMPLOYEE,)),
        (("managers", "staff"), (Role.EMPLOYEE, Role.MANAGER)),
        (("it-agents",), (Role.IT_SERVICE_DESK,)),
        (("people-advisors", "people-advisors"), (Role.PEOPLE_ADVISOR,)),
        (("Staff", "MANAGERS", "team-payments", "eng"), ()),
        (("workflow_worker", "workflow-worker", "workflow_workers"), ()),
    ],
)
def test_roles_from_groups(groups: tuple[str, ...], expected: tuple[Role, ...]) -> None:
    assert roles_from_groups(groups) == expected


def test_no_group_yields_workflow_worker() -> None:
    from tessaro_auth.roles import GROUP_TO_ROLE

    assert Role.WORKFLOW_WORKER not in GROUP_TO_ROLE.values()


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"is_active": False, "employee_id": None, "groups": ()}, MintReason.INACTIVE),
        ({"employee_id": None, "email": "bad"}, MintReason.MISSING_EMPLOYEE_ID),
        ({"employee_id": ""}, MintReason.MISSING_EMPLOYEE_ID),
        ({"employee_id": "TES-1007", "email": "bad"}, MintReason.MALFORMED_EMPLOYEE_ID),
        ({"employee_id": "TES-\uff10\uff11\uff10\uff10\uff17"}, MintReason.MALFORMED_EMPLOYEE_ID),
        ({"employee_id": "TES-01007\n"}, MintReason.MALFORMED_EMPLOYEE_ID),
        ({"email": "noor dekker@tessaro.example"}, MintReason.MALFORMED_EMAIL),
        ({"email": "a@b@c", "groups": ()}, MintReason.MALFORMED_EMAIL),
        ({"groups": ("team-payments",)}, MintReason.NO_ROLE),
    ],
)
def test_human_mint_refusals_in_order(
    adapter_signer: Signer,
    persona: DirectoryIdentity,
    change: dict[str, object],
    reason: MintReason,
) -> None:
    identity = replace(persona, **change)  # type: ignore[arg-type]
    with pytest.raises(MintRefused) as caught:
        issue_human_token(identity, RID, adapter_signer, NOW, 300)
    assert caught.value.reason is reason
    assert str(caught.value) == reason.value


@pytest.mark.parametrize(
    "request_id", ["", "ABCDEF0123456789abcdef0123456789", RID + "0", "x" * 32]
)
def test_human_mint_refuses_a_malformed_request_id(
    adapter_signer: Signer, persona: DirectoryIdentity, request_id: str
) -> None:
    with pytest.raises(MintRefused) as caught:
        issue_human_token(replace(persona, groups=()), request_id, adapter_signer, NOW, 300)
    assert caught.value.reason is MintReason.MALFORMED_REQUEST_ID


def test_worker_token_claims(worker_signer: Signer) -> None:
    token = issue_worker_token("joiner-TES-01042", "TES-01003", RID, worker_signer, NOW, 120)

    assert jwt.get_unverified_header(token) == {"alg": "EdDSA", "kid": "worker-1", "typ": "JWT"}
    claims = _claims(token)
    iat = int(NOW.timestamp())
    assert claims == {
        "iss": "tessaro-jml-worker",
        "aud": "tessaro-tools",
        "sub": "workflow:joiner-TES-01042",
        "kind": "workflow_worker",
        "roles": ["workflow_worker"],
        "on_behalf_of": "TES-01003",
        "request_id": RID,
        "jti": claims["jti"],
        "iat": iat,
        "exp": iat + 120,
    }


def test_worker_token_without_approver_has_no_on_behalf_of(worker_signer: Signer) -> None:
    token = issue_worker_token("leaver-TES-01020-2026-11-30", None, RID, worker_signer, NOW, 300)
    assert "on_behalf_of" not in _claims(token)


@pytest.mark.parametrize(
    ("workflow_id", "on_behalf_of", "request_id", "reason"),
    [
        ("onboard-TES-01042", None, RID, MintReason.MALFORMED_WORKFLOW_ID),
        ("joiner-TES-1042", None, RID, MintReason.MALFORMED_WORKFLOW_ID),
        ("joiner-TES-01042-2026-02-30", None, RID, MintReason.MALFORMED_WORKFLOW_ID),
        ("joiner-TES-01042-2026-13-01", "nobody", "bad", MintReason.MALFORMED_WORKFLOW_ID),
        ("mover-TES-01042", "maria", "bad", MintReason.MALFORMED_ON_BEHALF_OF),
        ("mover-TES-01042", "", RID, MintReason.MALFORMED_ON_BEHALF_OF),
        ("mover-TES-01042", None, "bad", MintReason.MALFORMED_REQUEST_ID),
    ],
)
def test_worker_mint_refusals(
    worker_signer: Signer,
    workflow_id: str,
    on_behalf_of: str | None,
    request_id: str,
    reason: MintReason,
) -> None:
    with pytest.raises(MintRefused) as caught:
        issue_worker_token(workflow_id, on_behalf_of, request_id, worker_signer, NOW, 300)
    assert caught.value.reason is reason


def test_a_human_signer_cannot_mint_a_worker_token(adapter_signer: Signer) -> None:
    with pytest.raises(MintRefused) as caught:
        issue_worker_token("joiner-TES-01042", None, RID, adapter_signer, NOW, 300)
    assert caught.value.reason is MintReason.WRONG_SIGNER_KIND


def test_a_worker_signer_cannot_mint_a_human_token(
    worker_signer: Signer, persona: DirectoryIdentity
) -> None:
    with pytest.raises(MintRefused) as caught:
        issue_human_token(persona, RID, worker_signer, NOW, 300)
    assert caught.value.reason is MintReason.WRONG_SIGNER_KIND


@pytest.mark.parametrize("ttl", [0, 601, -5])
def test_mint_rejects_a_ttl_outside_1_to_600(
    adapter_signer: Signer, persona: DirectoryIdentity, ttl: int
) -> None:
    with pytest.raises(ValueError, match="ttl_seconds"):
        issue_human_token(persona, RID, adapter_signer, NOW, ttl)


def test_mint_rejects_a_naive_clock(adapter_signer: Signer, persona: DirectoryIdentity) -> None:
    with pytest.raises(ValueError, match="timezone"):
        issue_human_token(persona, RID, adapter_signer, datetime(2026, 10, 8), 300)


def test_iat_is_truncated_to_whole_seconds(
    adapter_signer: Signer, persona: DirectoryIdentity
) -> None:
    now = datetime(2026, 10, 8, 9, 30, 0, 999_999, tzinfo=UTC)
    claims = _claims(issue_human_token(persona, RID, adapter_signer, now, 600))
    assert claims["iat"] == int(datetime(2026, 10, 8, 9, 30, tzinfo=UTC).timestamp())
    assert claims["exp"] == claims["iat"] + 600
