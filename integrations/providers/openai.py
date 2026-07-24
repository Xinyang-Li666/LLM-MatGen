"""Optional OpenAI adapter for the provider-neutral protocol."""
from __future__ import annotations
from typing import Any, Sequence

class OpenAIProvider:
    def __init__(self, model: str, api_key: str | None = None, client: Any = None):
        self.model, self.api_key, self._client = model, api_key, client

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise RuntimeError('OpenAI support is unavailable; install `llm-matgen[openai]`') from exc
            self._client = OpenAI(api_key=self.api_key)
        return self._client

    def complete(self, messages: Sequence[Any], tools: Sequence[Any]):
        from llm_matgen.orchestration.models import ModelTurn, ToolCall
        payload = [{"role": getattr(m, "role", "user"), "content": getattr(m, "content", "")} for m in messages]
        defs = [{"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.input_schema}} for t in tools]
        try:
            response = self._get_client().chat.completions.create(model=self.model, messages=payload, tools=defs)
        except Exception as exc:
            raise RuntimeError(f"openai_api_error: {exc}") from exc
        msg = response.choices[0].message
        calls = [ToolCall(call_id=c.id, name=c.function.name, arguments=__import__('json').loads(c.function.arguments)) for c in (msg.tool_calls or [])]
        return ModelTurn(text=msg.content, tool_calls=calls, finish_reason=response.choices[0].finish_reason or "unknown")
