import json

import pytest


def _server(tmp_path):
    from llm_matgen.mcp.server import MCPServer
    from llm_matgen.orchestration.tools import default_tool_registry

    return MCPServer(default_tool_registry(tmp_path), tmp_path)


def test_tool_call_rejects_untyped_extra_arguments(tmp_path):
    response = _server(tmp_path).handle({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "cases_status", "arguments": {"arguments": ["scan"]}},
    })
    payload = response["result"]["structuredContent"]
    assert response["result"]["isError"] is True
    assert payload["error_code"] == "invalid_arguments"


def test_resource_denies_path_escape(tmp_path):
    from llm_matgen.mcp.server import MCPProtocolError

    with pytest.raises(MCPProtocolError, match="outside output root"):
        _server(tmp_path).handle({
            "jsonrpc": "2.0", "id": 1, "method": "resources/read",
            "params": {"uri": "artifact://../secret.txt"},
        })


def test_resource_denies_unregistered_file(tmp_path):
    from llm_matgen.mcp.server import MCPProtocolError

    (tmp_path / "orphan.txt").write_text("not registered", encoding="utf-8")
    with pytest.raises(MCPProtocolError, match="not registered"):
        _server(tmp_path).handle({
            "jsonrpc": "2.0", "id": 1, "method": "resources/read",
            "params": {"uri": "artifact://orphan.txt"},
        })


def test_registered_artifact_can_be_read(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    artifact = run / "summary.txt"
    artifact.write_text("safe", encoding="utf-8")
    (run / "manifest.json").write_text(
        json.dumps({"artifacts": [{"path": "summary.txt"}]}), encoding="utf-8"
    )
    response = _server(tmp_path).handle({
        "jsonrpc": "2.0", "id": 1, "method": "resources/read",
        "params": {"uri": "artifact://run/summary.txt"},
    })
    assert response["result"]["contents"][0]["text"] == "safe"


def test_surface_schema_is_typed_and_promises_candidate_metadata(tmp_path):
    tools = {tool.name: tool for tool in _server(tmp_path).registry.definitions()}
    surface = tools["generate_surface"]
    assert {"structure", "miller_indices", "cell_shape"} <= set(surface.input_schema["properties"])
    assert surface.input_schema["additionalProperties"] is False
    assert "candidate metadata" in surface.description
