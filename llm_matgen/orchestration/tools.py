"""Deterministic tool definitions and safe execution facade."""
from __future__ import annotations
import inspect
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Type
from pydantic import BaseModel, ValidationError, create_model
from .models import ToolResult

class ToolError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message); self.code = code

def _schema(model_or_schema: Any) -> dict[str, Any]:
    if model_or_schema is None: return {"type":"object", "properties":{}, "additionalProperties":False}
    if isinstance(model_or_schema, dict):
        out = dict(model_or_schema)
    elif isinstance(model_or_schema, type) and issubclass(model_or_schema, BaseModel):
        out = model_or_schema.model_json_schema()
    else: out = {"type":"object", "properties":{}}
    out.setdefault("type", "object")
    def seal(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node: node["additionalProperties"] = False
            for value in node.values(): seal(value)
        elif isinstance(node, list):
            for value in node: seal(value)
    seal(out)
    out["additionalProperties"] = False
    # Keep nested object schemas closed as well; this prevents provider-side
    # argument smuggling when a Pydantic model contains dictionaries/models.
    def close(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object": node["additionalProperties"] = False
            for value in node.values(): close(value)
        elif isinstance(node, list):
            for value in node: close(value)
    close(out)
    return out

@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    handler: Callable[..., Any]
    mutates_files: bool = False

    def __post_init__(self):
        if not self.name or not self.description: raise ValueError("tool name and description are required")
        if not callable(self.handler): raise TypeError("handler must be callable")
        object.__setattr__(self, "input_schema", _schema(self.input_schema))
        object.__setattr__(self, "output_schema", _schema(self.output_schema))
        props = set(self.input_schema.get("properties", {}))
        params = inspect.signature(self.handler).parameters
        if props and not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
            accepted = {p.name for p in params.values() if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)}
            if not props.issubset(accepted):
                raise ValueError(f"tool schema parameters do not match handler signature: {sorted(props - accepted)}")

class ToolRegistry:
    def __init__(self, definitions: list[ToolDefinition] | None = None):
        self._items: dict[str, ToolDefinition] = {}
        for item in definitions or []: self.register(item)
    def register(self, definition: ToolDefinition) -> ToolDefinition:
        if definition.name in self._items: raise ValueError(f"duplicate tool name: {definition.name}")
        self._items[definition.name] = definition; return definition
    def get(self, name: str) -> ToolDefinition | None: return self._items.get(name)
    def definitions(self) -> tuple[ToolDefinition, ...]: return tuple(self._items.values())
    def list_tools(self) -> tuple[ToolDefinition, ...]: return self.definitions()
    def execute(self, name: str, arguments: Mapping[str, Any] | None = None) -> ToolResult:
        return ToolExecutor(self).call(name, arguments or {})

class ToolExecutor:
    def __init__(self, registry: ToolRegistry): self.registry = registry
    def call(self, name: str, arguments: Mapping[str, Any] | None = None, call_id: str = "") -> ToolResult:
        tool = self.registry.get(name)
        if tool is None: return ToolResult(call_id=call_id, ok=False, summary=f"unknown tool: {name}", error_code="tool_not_found")
        args = dict(arguments or {})
        try:
            result = tool.handler(**args)
            if isinstance(result, ToolResult): return result.model_copy(update={"call_id": call_id or result.call_id})
            if isinstance(result, BaseModel): payload = result.model_dump(mode="json")
            elif isinstance(result, Mapping): payload = dict(result)
            else: payload = {"value": result}
            refs = payload.pop("artifact_refs", []) if isinstance(payload, dict) else []
            summary = payload.pop("summary", "tool completed") if isinstance(payload, dict) else "tool completed"
            return ToolResult(call_id=call_id, ok=True, summary=str(summary), structured_content=payload, artifact_refs=list(refs or []))
        except ValidationError as exc:
            return ToolResult(call_id=call_id, ok=False, summary="invalid tool arguments", error_code="invalid_arguments", structured_content={"details": json.loads(exc.json())})
        except ToolError as exc:
            return ToolResult(call_id=call_id, ok=False, summary=str(exc), error_code=exc.code)
        except TypeError as exc:
            return ToolResult(call_id=call_id, ok=False, summary=str(exc), error_code="invalid_arguments")
        except Exception as exc:
            return ToolResult(call_id=call_id, ok=False, summary=str(exc), error_code="handler_error")

def _placeholder(name: str):
    def handler(**kwargs): raise ToolError("not_configured", f"{name} tool requires an application context")
    return handler

def default_tool_registry(output_root: Any = "output") -> ToolRegistry:
    names = ["generate", "search", "download", "properties", "check", "export", "db_query"]
    descriptions = {
        "generate":"Generate structures with one of the nine structure generators.", "search":"Search local or Materials Project sources.",
        "download":"Download a referenced structure into the local cache.", "properties":"Query cached material properties.",
        "check":"Run lightweight structural checks.", "export":"Export structures as POSCAR, CIF, or LAMMPS data.", "db_query":"Query local database snapshots."}
    return ToolRegistry([ToolDefinition(n, descriptions[n], {"type":"object","properties":{},"additionalProperties":False}, {"type":"object","properties":{},"additionalProperties":False}, _placeholder(n), n in {"generate","download","export"}) for n in names])
