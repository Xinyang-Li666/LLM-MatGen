"""Bounded provider-neutral LLM/tool workflow runner."""
from __future__ import annotations
import json
from collections import defaultdict
from typing import Any
from .models import AgentResult, Message, ModelTurn, ToolCall
from .tools import ToolExecutor, ToolRegistry
from .prompts import build_system_prompt

class WorkflowRunner:
    def __init__(self, provider: Any, registry: ToolRegistry, *, max_turns: int = 8, max_tool_calls: int = 32, max_generated_structures: int = 1000, system_prompt: str | None = None, read_only: bool = False):
        self.provider, self.registry = provider, registry; self.executor = ToolExecutor(registry)
        self.max_turns, self.max_tool_calls, self.max_generated_structures = max_turns, max_tool_calls, max_generated_structures
        self.system_prompt, self.read_only = build_system_prompt(system_prompt), read_only
    def ask(self, user_input: str) -> AgentResult:
        messages = [Message(role="system", content=self.system_prompt), Message(role="user", content=user_input)]
        results=[]; seen_ids=set(); repeated=defaultdict(int); calls=0; generated=0
        for turn_no in range(1, self.max_turns + 1):
            try: turn = self.provider.complete(messages, self.registry.definitions())
            except Exception as exc: return AgentResult(ok=False, error_code="provider_error", text=str(exc), turns=turn_no, tool_calls=calls, tool_results=results, messages=messages)
            if not isinstance(turn, ModelTurn): turn = ModelTurn.model_validate(turn)
            if not turn.tool_calls:
                return AgentResult(ok=True, text=turn.text, turns=turn_no, tool_calls=calls, generated_structures=generated, tool_results=results, messages=messages)
            for call in turn.tool_calls:
                if call.call_id in seen_ids: return AgentResult(ok=False,error_code="duplicate_call_id",text="duplicate tool call id",turns=turn_no,tool_calls=calls,tool_results=results,messages=messages)
                seen_ids.add(call.call_id); calls += 1
                if calls > self.max_tool_calls: return AgentResult(ok=False,error_code="max_tool_calls",text="tool call limit reached",turns=turn_no,tool_calls=calls,tool_results=results,messages=messages)
                key = (call.name, json.dumps(call.arguments, sort_keys=True, default=str))
                tool = self.registry.get(call.name)
                if tool is None: result = self.executor.call(call.name, call.arguments, call.call_id)
                elif self.read_only and tool.mutates_files: result = self.executor.call(call.name, {}, call.call_id); result.ok=False; result.error_code="read_only_denied"
                else: result = self.executor.call(call.name, call.arguments, call.call_id)
                results.append(result); generated += int(result.structured_content.get("generated_count", 0))
                if result.ok:
                    repeated[key] = 0
                else:
                    repeated[key] += 1
                    if repeated[key] >= 3:
                        return AgentResult(ok=False,error_code="repeated_tool_failure",text="repeated identical tool call failed three times",turns=turn_no,tool_calls=calls,generated_structures=generated,tool_results=results,messages=messages)
                if generated > self.max_generated_structures: return AgentResult(ok=False,error_code="max_generated_structures",text="generation limit reached",turns=turn_no,tool_calls=calls,generated_structures=generated,tool_results=results,messages=messages)
                messages.append(Message(role="assistant", content=turn.text or ""))
                messages.append(Message(role="tool", content=result.model_dump_json(), tool_call_id=call.call_id))
        return AgentResult(ok=False,error_code="max_turns",text="maximum workflow turns reached",turns=self.max_turns,tool_calls=calls,generated_structures=generated,tool_results=results,messages=messages)
