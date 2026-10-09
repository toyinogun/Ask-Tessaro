"""The OpenAI chat completion request, as far as masking needs to understand it.

Fields the proxy does not know are dropped, so nothing unmasked slips through: at message
level everything but the known fields, at top level everything but `FORWARDED_PARAMETERS`.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

FORWARDED_PARAMETERS = frozenset(
    {
        "tools",  # definitions we write, trusted static content (spec 0006 AC-2)
        "tool_choice",
        "parallel_tool_calls",
        "response_format",
        "temperature",
        "top_p",
        "max_tokens",
        "max_completion_tokens",
        "n",
        "stop",
        "seed",
        "presence_penalty",
        "frequency_penalty",
        "logit_bias",
        "logprobs",
        "top_logprobs",
    }
)
"""Top level parameters forwarded as they are; free text ones (`prediction`, `metadata`) are not."""


class ContentPart(BaseModel):
    """One part of a content array. Only `text` parts are accepted (spec 0006 AC-9)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    type: str
    text: str | None = None


class FunctionCall(BaseModel):
    """The function an assistant tool call named, and its JSON arguments string."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str
    arguments: str


class ToolCall(BaseModel):
    """One tool call made by the assistant in an earlier turn."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str
    type: Literal["function"] = "function"
    function: FunctionCall


class ChatMessage(BaseModel):
    """One message. `name` is accepted but never sent upstream (it can hold a person's name)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | tuple[ContentPart, ...] | None = None
    name: str | None = None
    tool_calls: tuple[ToolCall, ...] | None = None
    tool_call_id: str | None = None


class ChatRequest(BaseModel):
    """A chat completion request. Extra top level fields are kept; only some are forwarded."""

    # Any: OpenAI parameters the proxy passes through untouched have open ended JSON shapes.
    model_config = ConfigDict(frozen=True, extra="allow")

    model: str
    messages: tuple[ChatMessage, ...] = Field(min_length=1)
    stream: bool | None = None
    user: str | None = None

    def passthrough(self) -> dict[str, Any]:
        """The `FORWARDED_PARAMETERS` the caller set, unchanged; every other extra is dropped."""
        return {k: v for k, v in (self.model_extra or {}).items() if k in FORWARDED_PARAMETERS}
