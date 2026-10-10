"""`PlaywrightSignIn`: the `SignInBrowser` as headless Chromium (`just smoke-deps` installs it).

Exercised only by `just identity-smoke` against the live systems; the unit tests use a fake.
"""

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, async_playwright

from tessaro_seed.smoke.identity import SmokeError

ZULIP_BUTTON = "Log in with Tessaro"
IDENTIFIER_INPUT = 'input[name="uidField"]'
# The password stage's own field (the first stage also holds hidden helpers for password managers).
PASSWORD_INPUT = "#ak-stage-password-input"  # noqa: S105 (a CSS selector, not a secret)
STEP_MS = 30_000


async def _authentik_sign_in(page: Page, username: str, password: str) -> None:
    await page.locator(IDENTIFIER_INPUT).fill(username)
    await page.locator(IDENTIFIER_INPUT).press("Enter")
    await page.locator(PASSWORD_INPUT).fill(password)
    await page.locator(PASSWORD_INPUT).press("Enter")


async def _session_email(page: Page, site: str, username: str, password: str) -> str | None:
    await page.goto(site)
    await page.get_by_role("button", name=ZULIP_BUTTON).click()
    await _authentik_sign_in(page, username, password)
    # Back on Zulip; "load", not "networkidle", since the app long polls for events.
    await page.wait_for_url(lambda url: url.startswith(f"{site}/"))
    response = await page.request.get(f"{site}/json/users/me")
    if not response.ok:
        return None
    email = (await response.json()).get("email")
    return str(email) if email is not None else None


class PlaywrightSignIn:
    """Each call opens a fresh browser context, so no session leaks from one check to the next."""

    async def zulip_session_email(self, site: str, username: str, password: str) -> str | None:
        """Sign in through Zulip's OIDC button and read `/json/users/me` in that session."""
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            page = await browser.new_page()
            page.set_default_timeout(STEP_MS)
            try:
                return await _session_email(page, site.rstrip("/"), username, password)
            except PlaywrightError as error:
                first_line = str(error).splitlines()[0] if str(error) else type(error).__name__
                raise SmokeError(f"{first_line} (stopped on {page.url})") from error
            finally:
                await browser.close()
