"""Provider-neutral contracts used by the orchestration layer."""
from __future__ import annotations

from typing import Any, Literal, Protocol, Sequence
from pydantic import BaseModel, ConfigDict, Field
from llm_matgen.generators.models import JsonValue

class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None

class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid")
    call_id: str
    name: str
    arguments: dict[str, JsonValue] = Field(default_factory=dict)

class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    call_id: str
    ok: bool
    summary: str
    structured_content: dict[str, JsonValue] = Field(default_factory=dict)
    artifact_refs: list[str] = Field(default_factory=list)
    error_code: str | None = None

class ModelTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str = "stop"

class AgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str | None = None
    tool_results: list[ToolResult] = Field(default_factory=list)
    turns: int = 0
    tool_calls: int = 0
    generated_structures: int = 0
    ok: bool = True
    error_code: str | None = None
    messages: list[Message] = Field(default_factory=list)

class LLMProvider(Protocol):
    def complete(self, messages: Sequence[Message], tools: Sequence[Any]) -> ModelTurn: ...
