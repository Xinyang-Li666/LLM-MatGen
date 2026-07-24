"""Optional Anthropic adapter for the provider-neutral protocol."""
from __future__ import annotations
from typing import Any, Sequence

class AnthropicProvider:
    def __init__(self, model: str, api_key: str | None = None, client: Any = None):
        self.model = model
        self._client = client
        self.api_key = api_key

    def _get_client(self):
        if self._client is None:
            try:
                from anthropic import Anthropic
            except ImportError as exc:
                raise RuntimeError('Anthropic support is unavailable; install `llm-matgen[anthropic]`') from exc
            self._client = Anthropic(api_key=self.api_key)
        return self._client

    def complete(self, messages: Sequence[Any], tools: Sequence[Any]):
        from llm_matgen.orchestration.models import ModelTurn, ToolCall
        payload = [{"role": getattr(m, "role", "user"), "content": getattr(m, "content", "")} for m in messages]
        tool_defs = [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools]
        try:
            response = self._get_client().messages.create(model=self.model, messages=payload, tools=tool_defs)
        except Exception as exc:
            raise RuntimeError(f"anthropic_api_error: {exc}") from exc
        calls = []
        text = None
        for block in getattr(response, "content", []):
            if getattr(block, "type", None) == "text": text = (text or "") + block.text
            elif getattr(block, "type", None) == "tool_use": calls.append(ToolCall(call_id=block.id, name=block.name, arguments=block.input or {}))
        stop = getattr(response, "stop_reason", None) or "unknown"
        if stop not in {"end_turn", "tool_use", "max_tokens", "stop_sequence"}:
            raise RuntimeError(f"unknown_stop_reason: {stop}")
        return ModelTurn(text=text, tool_calls=calls, finish_reason=stop)
