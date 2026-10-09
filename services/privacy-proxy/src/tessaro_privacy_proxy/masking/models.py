"""The OpenAI chat completion request, as far as masking needs to understand it.

Message level fields the proxy does not know are dropped (so nothing unmasked slips
through); top level parameters it does not know (`tools`, `temperature`, ...) pass through.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


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
    """A chat completion request. Extra top level fields are kept and forwarded as they are."""

    # Any: OpenAI parameters the proxy passes through untouched have open ended JSON shapes.
    model_config = ConfigDict(frozen=True, extra="allow")

    model: str
    messages: tuple[ChatMessage, ...] = Field(min_length=1)
    stream: bool | None = None
    user: str | None = None

    def passthrough(self) -> dict[str, Any]:
        """The top level fields the proxy forwards unchanged (everything it does not rewrite)."""
        return dict(self.model_extra or {})
