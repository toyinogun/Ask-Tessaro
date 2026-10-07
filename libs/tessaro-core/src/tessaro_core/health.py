"""Health routes: `/healthz` (process up) and `/readyz` (dependencies reachable)."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from tessaro_core.logging import get_logger


@dataclass(frozen=True)
class ReadinessCheck:
    """A named dependency probe. `probe` returns True when the dependency is reachable."""

    name: str
    probe: Callable[[], Awaitable[bool]]


async def _run(check: ReadinessCheck) -> bool:
    try:
        return await check.probe()
    except Exception:
        get_logger(__name__).warning("readiness_check_failed", check=check.name, exc_info=True)
        return False


def health_router(checks: Sequence[ReadinessCheck] = ()) -> APIRouter:
    router = APIRouter(tags=["health"])
    frozen_checks = tuple(checks)

    @router.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/readyz")
    async def readyz() -> JSONResponse:
        results = {check.name: await _run(check) for check in frozen_checks}
        ready = all(results.values())
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"status": "ready" if ready else "not_ready", "checks": results},
        )

    return router
