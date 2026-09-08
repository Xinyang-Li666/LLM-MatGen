def test_mcp_registry_exposes_typed_adsorption_tools_without_case_scan(tmp_path):
    from llm_matgen.orchestration.tools import default_tool_registry

    registry = default_tool_registry(tmp_path)
    tools = {item.name: item for item in registry.definitions()}
    assert {"generate_adsorption", "cases_status", "cases_query", "cases_inspect", "revision_import"} <= set(tools)
    assert "cases_scan" not in tools
    schema = tools["generate_adsorption"].input_schema
    assert {"slab", "adsorbate", "anchor_index"} <= set(schema["properties"])
    assert "arguments" not in schema["properties"]
    assert schema["additionalProperties"] is False


def test_mcp_viewer_resource_uses_html_mime_type(tmp_path):
    import json
    from llm_matgen.mcp.server import MCPServer
    from llm_matgen.orchestration.tools import default_tool_registry

    run = tmp_path / "run"
    run.mkdir()
    viewer = run / "viewer.html"
    viewer.write_text("<html></html>", encoding="utf-8")
    (run / "manifest.json").write_text(json.dumps({"artifacts": [{"path": "viewer.html"}]}), encoding="utf-8")
    response = MCPServer(default_tool_registry(tmp_path), tmp_path).handle({
        "jsonrpc": "2.0", "id": 1, "method": "resources/read", "params": {"uri": "artifact://run/viewer.html"},
    })
    assert response["result"]["contents"][0]["mimeType"] == "text/html"


def test_mcp_adsorption_returns_only_output_root_artifacts(tmp_path, monkeypatch):
    from pymatgen.core import Lattice, Molecule, Structure
    from pymatgen.io.vasp import Poscar

    monkeypatch.chdir(tmp_path)
    slab_path = tmp_path / "slab.vasp"
    adsorbate_path = tmp_path / "h.xyz"
    Poscar(Structure(Lattice.from_parameters(3, 3, 12, 90, 90, 90), ["Cu"], [[0.5, 0.5, 0.15]])).write_file(slab_path)
    Molecule(["H"], [[0, 0, 0]]).to(filename=adsorbate_path, fmt="xyz")

    from llm_matgen.orchestration.tools import default_tool_registry

    output = tmp_path / "output"
    result = default_tool_registry(output).execute("generate_adsorption", {
        "slab": str(slab_path),
        "adsorbate": str(adsorbate_path),
        "max_structures": 1,
        "site_types": ["top"],
    })
    assert result.ok is True
    assert result.artifact_refs
    assert all(reference.startswith("artifact://") for reference in result.artifact_refs)
    assert all((output / reference.removeprefix("artifact://")).is_file() for reference in result.artifact_refs)
