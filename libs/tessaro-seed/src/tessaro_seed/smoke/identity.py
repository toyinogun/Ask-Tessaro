"""The identity smoke checks as plain logic over a `SignInBrowser` (spec 0008 AC-14).

Check (a) lands first: the demo persona signs in to Zulip through Authentik and the session is
theirs. Before it, the email trust check: Authentik vouches for every email it sends Zulip, which
holds only while users cannot change their own. Checks (b) to (e) join here as the build thickens.
"""

from dataclasses import dataclass
from typing import Protocol

from tessaro_clients.authentik import AuthentikDirectory
from tessaro_clients.errors import ClientError
from tessaro_dataset import Dataset
from tessaro_dataset.exports.authentik import export_authentik

PERSONA_SIGN_IN = "a. demo persona signs in to Zulip through Authentik"
EMAIL_TRUST = "email trust: users cannot change their own Authentik email"


class SmokeError(Exception):
    """A smoke step could not run to the end (the browser got stuck, a page never loaded)."""


class SignInBrowser(Protocol):
    """A real browser session against Zulip and Authentik."""

    async def zulip_session_email(self, site: str, username: str, password: str) -> str | None:
        """Sign in through Zulip's "Log in with Tessaro" button; the session's email, or None."""
        ...


@dataclass(frozen=True)
class Persona:
    """The person the smoke signs in as, as the seed put them in Authentik."""

    employee_id: str
    username: str
    email: str
    groups: frozenset[str]


@dataclass(frozen=True)
class CheckResult:
    """One smoke check: its name, whether it passed and what was seen."""

    name: str
    passed: bool
    detail: str


def persona_of(dataset: Dataset) -> Persona:
    """The demo cast's persona (spec 0002 AC-15) with the username, email and groups seeded."""
    employee_id = dataset.cast("persona").id
    user = next(u for u in export_authentik(dataset).users if u.employee_id == employee_id)
    return Persona(employee_id, user.username, user.email, frozenset(user.groups))


async def _persona_sign_in(
    browser: SignInBrowser, site: str, persona: Persona, password: str
) -> CheckResult:
    try:
        email = await browser.zulip_session_email(site, persona.username, password)
    except SmokeError as error:
        return CheckResult(PERSONA_SIGN_IN, False, str(error))
    if email is None:
        return CheckResult(PERSONA_SIGN_IN, False, "no Zulip session after signing in")
    if email != persona.email:
        return CheckResult(PERSONA_SIGN_IN, False, f"session is {email}, not {persona.email}")
    return CheckResult(PERSONA_SIGN_IN, True, f"/json/users/me is {email}")


async def _email_trust(directory: AuthentikDirectory) -> CheckResult:
    try:
        allowed = await directory.users_can_change_email()
    except ClientError as error:
        return CheckResult(EMAIL_TRUST, False, str(error))
    if allowed:
        return CheckResult(EMAIL_TRUST, False, "default_user_change_email is on; turn it off")
    return CheckResult(EMAIL_TRUST, True, "default_user_change_email is off")


async def smoke_identity(
    browser: SignInBrowser,
    directory: AuthentikDirectory,
    site: str,
    persona: Persona,
    password: str,
) -> tuple[CheckResult, ...]:
    """Run every identity check in order; a failed check never stops the next one."""
    return (
        await _email_trust(directory),
        await _persona_sign_in(browser, site, persona, password),
    )
