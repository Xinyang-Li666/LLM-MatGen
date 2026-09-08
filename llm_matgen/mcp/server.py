"""JSON-RPC/stdio MCP server backed by the deterministic tool registry.

The implementation intentionally keeps the protocol adapter thin: schemas and
execution semantics come from :mod:`llm_matgen.orchestration`.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable


class MCPProtocolError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class MCPServer:
    protocol_version = "2024-11-05"

    def __init__(self, registry: Any, output_root: str | Path = "output"):
        self.registry = registry
        self.output_root = Path(output_root).resolve()
        self.output_root.mkdir(parents=True, exist_ok=True)
        self._manifest_artifacts: set[str] = set()

    def _tools(self) -> list[Any]:
        if hasattr(self.registry, "definitions"):
            return list(self.registry.definitions())
        if hasattr(self.registry, "list_tools"):
            return list(self.registry.list_tools())
        return list(self.registry.values())

    def _find(self, name: str) -> Any:
        if hasattr(self.registry, "get"):
            item = self.registry.get(name)
        else:
            item = next((x for x in self._tools() if getattr(x, "name", None) == name), None)
        if item is None:
            raise MCPProtocolError("tool_not_found", f"unknown tool: {name}")
        return item

    def _tool_payload(self, tool: Any) -> dict[str, Any]:
        schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", {})
        out = getattr(tool, "output_schema", None) or getattr(tool, "outputSchema", {})
        return {"name": tool.name, "description": tool.description,
                "inputSchema": schema, "outputSchema": out}

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(request, dict):
            raise MCPProtocolError("invalid_request", "request must be an object")
        method = request.get("method")
        req_id = request.get("id")
        params = request.get("params") or {}
        if method == "notifications/initialized":
            return None
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": req_id, "result": {
                "protocolVersion": self.protocol_version,
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": "llm-matgen", "version": "0.1.0"}}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id,
                    "result": {"tools": [self._tool_payload(t) for t in self._tools()]}}
        if method == "tools/call":
            name = params.get("name")
            if not isinstance(name, str):
                raise MCPProtocolError("invalid_params", "tools/call requires name")
            args = params.get("arguments") or {}
            tool = self._find(name)
            try:
                if hasattr(self.registry, "execute"):
                    result = self.registry.execute(name, args)
                else:
                    result = tool.handler(**args)
                payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
                return {"jsonrpc": "2.0", "id": req_id, "result": {
                    "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
                    "structuredContent": payload,
                    "isError": bool(getattr(result, "ok", True) is False)}}
            except Exception as exc:
                return {"jsonrpc": "2.0", "id": req_id, "error": {
                    "code": "tool_error", "message": str(exc)}}
        if method == "resources/read":
            uri = params.get("uri")
            if not isinstance(uri, str):
                raise MCPProtocolError("invalid_params", "resources/read requires uri")
            return self._read_resource(req_id, uri)
        raise MCPProtocolError("method_not_found", f"unsupported method: {method}")

    # Friendly aliases used by embedders and tests.
    handle_request = handle
    process_request = handle

    def _read_resource(self, req_id: Any, uri: str) -> dict[str, Any]:
        if uri.startswith("file://"):
            raw = uri[7:]
        elif uri.startswith("artifact://"):
            raw = uri[len("artifact://"):]
        elif uri.startswith("llm-matgen://artifact/"):
            raw = uri[len("llm-matgen://artifact/"):]
        else:
            raise MCPProtocolError("invalid_uri", "only artifact:// or file:// URIs are supported")
        path = (self.output_root / raw).resolve()
        if not path.is_relative_to(self.output_root):
            raise MCPProtocolError("path_denied", "resource is outside output root")
        if not path.is_file():
            raise MCPProtocolError("not_found", "resource does not exist")
        manifest = next((p / "manifest.json" for p in [path.parent, *path.parents]
                         if p.is_relative_to(self.output_root) and (p / "manifest.json").is_file()), None)
        if manifest is None and path.name != "manifest.json":
            raise MCPProtocolError("unregistered_artifact", "resource is not registered in a manifest")
        if manifest is not None and path.name != "manifest.json":
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
                allowed = {str((manifest.parent / a.get("path", "")).resolve())
                           for a in data.get("artifacts", []) if isinstance(a, dict)}
                if str(path) not in allowed:
                    raise MCPProtocolError("unregistered_artifact", "resource is not listed in manifest")
            except MCPProtocolError:
                raise
            except Exception as exc:
                raise MCPProtocolError("invalid_manifest", "manifest could not be read") from exc
        text = path.read_text(encoding="utf-8")
        mime_type = {
            ".html": "text/html",
            ".json": "application/json",
        }.get(path.suffix.lower(), "text/plain")
        return {"jsonrpc": "2.0", "id": req_id, "result": {"contents": [{
            "uri": uri, "mimeType": mime_type,
            "text": text}]}}


def serve_stdio(server: MCPServer, input_stream: Any = None, output_stream: Any = None) -> None:
    import sys
    inp, out = input_stream or sys.stdin, output_stream or sys.stdout
    for line in inp:
        if not line.strip():
            continue
        try:
            response = server.handle(json.loads(line))
            if response is not None:
                out.write(json.dumps(response, ensure_ascii=False) + "\n")
                out.flush()
        except MCPProtocolError as exc:
            out.write(json.dumps({"jsonrpc": "2.0", "id": None,
                                  "error": {"code": exc.code, "message": exc.message}}) + "\n")
            out.flush()
