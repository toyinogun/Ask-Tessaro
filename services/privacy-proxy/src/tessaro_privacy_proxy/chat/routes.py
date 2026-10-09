"""`POST /v1/chat/completions`: check, mask, call the model, restore (spec 0006 AC-1)."""

import hmac
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from tessaro_core import get_logger
from tessaro_privacy_proxy.chat.errors import (
    INVALID_REQUEST,
    ApiError,
    ErrorSpec,
    error_response,
    to_error_spec,
)
from tessaro_privacy_proxy.masking.entities import EntityType
from tessaro_privacy_proxy.masking.mask import Masker
from tessaro_privacy_proxy.masking.models import ChatRequest
from tessaro_privacy_proxy.masking.ports import MappingStore
from tessaro_privacy_proxy.masking.restore import restore_response
from tessaro_privacy_proxy.upstream.client import UpstreamClient, UpstreamError

CONVERSATION_HEADER = "X-Conversation-ID"
MAX_BODY_BYTES = 1024 * 1024
_CONVERSATION_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}")

UNAUTHORIZED = ErrorSpec(401, "invalid_api_key", "missing or wrong API key", "authentication_error")
NO_CONVERSATION = ErrorSpec(400, "missing_conversation_id", f"{CONVERSATION_HEADER} is required")
TOO_LARGE = ErrorSpec(413, "request_too_large", "the request body is over 1 MiB")
NO_STREAMING = ErrorSpec(400, "streaming_not_supported", "set stream to false")
BAD_MODEL = ErrorSpec(400, "model_not_allowed", "this model is not allowed")

log = get_logger(__name__)


@dataclass(frozen=True)
class ChatService:
    """Everything the route needs, wired by `build_app`."""

    masker: Masker
    store: MappingStore
    upstream: UpstreamClient
    client_key: str
    allowed_models: frozenset[str]


def _check_key(request: Request, expected: str) -> None:
    scheme, _, presented = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        presented.strip().encode(), expected.encode()
    ):
        raise ApiError(UNAUTHORIZED)


def _conversation_id(request: Request) -> str:
    value = request.headers.get(CONVERSATION_HEADER, "")
    if _CONVERSATION_ID.fullmatch(value) is None:
        raise ApiError(NO_CONVERSATION)
    return value


async def _read_body(request: Request) -> bytes:
    declared = request.headers.get("Content-Length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise ApiError(TOO_LARGE)
    received = bytearray()
    async for piece in request.stream():
        received.extend(piece)
        if len(received) > MAX_BODY_BYTES:
            raise ApiError(TOO_LARGE)
    return bytes(received)


def _parse(body: bytes, allowed_models: frozenset[str]) -> ChatRequest:
    try:
        parsed = ChatRequest.model_validate_json(body)
    except ValidationError as exc:
        raise ApiError(INVALID_REQUEST) from exc
    if parsed.stream:
        raise ApiError(NO_STREAMING)
    if parsed.model not in allowed_models:
        raise ApiError(BAD_MODEL)
    return parsed


def _counts(counts: Mapping[EntityType, int]) -> dict[str, int]:
    return {str(t): n for t, n in sorted(counts.items())}


def chat_router(service: ChatService) -> APIRouter:
    """The OpenAI compatible chat completions route."""
    router = APIRouter(tags=["chat"])

    @router.post("/v1/chat/completions")
    async def chat_completions(request: Request) -> JSONResponse:
        """Mask the request, call the model, restore the answer; refuse rather than leak."""
        started = time.perf_counter()
        conversation_id: str | None = None
        try:
            _check_key(request, service.client_key)
            conversation_id = _conversation_id(request)
            parsed = _parse(await _read_body(request), service.allowed_models)
            masked = await service.masker.mask_request(parsed, conversation_id)
            status, answer = await service.upstream.complete(masked.body)
            restored = await restore_response(answer, conversation_id, service.store)
        except Exception as exc:
            error = to_error_spec(exc)
            log.warning(
                "model_call_failed",
                conversation_id=conversation_id,
                code=error.code,
                error=type(exc).__name__,
                upstream_status=exc.status if isinstance(exc, UpstreamError) else None,
                duration_ms=round((time.perf_counter() - started) * 1000),
            )
            return error_response(error)
        for placeholder in restored.unknown:
            log.warning(
                "unknown_placeholder", conversation_id=conversation_id, placeholder=placeholder
            )
        log.info(
            "model_call",
            conversation_id=conversation_id,
            model=parsed.model,
            entities=_counts(masked.counts),
            upstream_status=status,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        return JSONResponse(content=dict(restored.body))

    return router
