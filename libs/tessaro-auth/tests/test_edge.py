"""`principal_from_headers`: one fixed 401, reasons in logs, request ID binding (AC-11, AC-12)."""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
import structlog
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from structlog.testing import capture_logs

from tessaro_auth.claims import Principal
from tessaro_auth.edge import principal_from_headers
from tessaro_auth.issue import DirectoryIdentity, issue_human_token
from tessaro_auth.keys import KeySet, Signer

NOW = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)
RID = "0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def _clean_context() -> Iterator[None]:
    structlog.contextvars.clear_contextvars()
    yield
    structlog.contextvars.clear_contextvars()


@pytest.fixture
def token(adapter_signer: Signer, persona: DirectoryIdentity) -> str:
    return issue_human_token(persona, RID, adapter_signer, NOW, 300)


def rejected(headers: dict[str, str], keyset: KeySet, now: datetime = NOW) -> HTTPException:
    with pytest.raises(HTTPException) as caught:
        principal_from_headers(headers, keyset, now)
    return caught.value


def test_valid_bearer_returns_the_principal(token: str, keyset: KeySet) -> None:
    principal = principal_from_headers({"Authorization": f"Bearer {token}"}, keyset, NOW)
    assert principal.request_id == RID


def test_scheme_and_header_name_are_case_insensitive(token: str, keyset: KeySet) -> None:
    assert principal_from_headers({"authorization": f"bearer {token}"}, keyset, NOW)
    assert principal_from_headers(Headers({"AUTHORIZATION": f"BEARER {token}"}), keyset, NOW)


@pytest.mark.parametrize(
    ("headers", "reason"),
    [
        ({}, "missing_token"),
        ({"Authorization": "Basic dXNlcjpwYXNz"}, "not_bearer"),
        ({"Authorization": "Bearer "}, "not_bearer"),
        ({"Authorization": "Bearer"}, "not_bearer"),
        ({"Authorization": "Bearer abc.def"}, "malformed"),
    ],
)
def test_every_failure_is_the_same_401(
    keyset: KeySet, headers: dict[str, str], reason: str
) -> None:
    with capture_logs() as logs:
        error = rejected(headers, keyset)
    assert error.status_code == 401
    assert error.detail == "invalid token"
    assert error.headers == {"WWW-Authenticate": 'Bearer error="invalid_token"'}
    assert logs == [
        {"event": "token_rejected", "reason": reason, "request_id": None, "log_level": "warning"}
    ]


def test_expired_token_logs_the_reason_and_never_the_token(token: str, keyset: KeySet) -> None:
    structlog.contextvars.bind_contextvars(request_id="feedfacefeedfacefeedfacefeedface")
    with capture_logs() as logs:
        error = rejected({"Authorization": f"Bearer {token}"}, keyset, NOW + timedelta(hours=1))
    assert error.detail == "invalid token"
    assert logs[0]["reason"] == "expired"
    assert logs[0]["request_id"] == "feedfacefeedfacefeedfacefeedface"
    assert token not in repr(logs)
    assert error.__cause__ is None


def test_rejection_falls_back_to_a_cut_header_request_id(keyset: KeySet) -> None:
    with capture_logs() as logs:
        rejected({"X-Request-ID": "r" * 500}, keyset)
    assert logs[0]["request_id"] == "r" * 64


def test_success_binds_the_token_request_id(token: str, keyset: KeySet) -> None:
    principal_from_headers({"Authorization": f"Bearer {token}"}, keyset, NOW)
    assert structlog.contextvars.get_contextvars()["request_id"] == RID


def test_matching_header_request_id_logs_nothing(token: str, keyset: KeySet) -> None:
    with capture_logs() as logs:
        principal_from_headers(
            {"Authorization": f"Bearer {token}", "X-Request-ID": RID}, keyset, NOW
        )
    assert logs == []


def test_mismatched_header_request_id_is_flagged(token: str, keyset: KeySet) -> None:
    with capture_logs() as logs:
        principal_from_headers(
            {"Authorization": f"Bearer {token}", "X-Request-ID": "x" * 300}, keyset, NOW
        )
    assert logs == [
        {
            "event": "request_id_mismatch",
            "request_id": RID,
            "header_request_id": "x" * 64,
            "log_level": "warning",
        }
    ]


def test_defaults_to_the_wall_clock(adapter_signer: Signer, keyset: KeySet) -> None:
    identity = DirectoryIdentity(
        employee_id="TES-01007", email="a@b", groups=("staff",), is_active=True
    )
    live = issue_human_token(identity, RID, adapter_signer, datetime.now(UTC), 300)
    assert principal_from_headers({"Authorization": f"Bearer {live}"}, keyset)


def test_fastapi_route_returns_the_fixed_401(token: str, keyset: KeySet) -> None:
    app = FastAPI()

    @app.get("/whoami")
    def whoami(request: Request) -> dict[str, str]:
        principal: Principal = principal_from_headers(request.headers, keyset, NOW)
        return {"kind": principal.kind.value}

    client = TestClient(app)
    ok = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
    assert ok.json() == {"kind": "human"}
    denied = client.get("/whoami", headers={"Authorization": "Basic abc"})
    assert denied.status_code == 401
    assert denied.json() == {"detail": "invalid token"}
    assert denied.headers["www-authenticate"] == 'Bearer error="invalid_token"'
