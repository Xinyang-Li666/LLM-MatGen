import json
from pathlib import Path


def test_cases_help_exposes_read_only_case_commands():
    from llm_matgen.__main__ import build_parser

    parser = build_parser()
    try:
        parser.parse_args(["cases", "--help"])
    except SystemExit as exc:
        assert exc.code == 0


def test_cases_status_outputs_json(tmp_path: Path, capsys):
    from llm_matgen.__main__ import main

    assert main(["cases", "status", "--store-root", str(tmp_path / "store")]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"]["index_revision"] == 0


def test_cases_scan_uses_named_local_source(tmp_path: Path, monkeypatch, capsys):
    from llm_matgen.__main__ import main

    root = tmp_path / "cases"
    root.mkdir()
    (root / "POSCAR").write_text("root", encoding="utf-8")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"adsorption": {"sources": [{"type": "local", "name": "demo", "root": str(root)}]}}), encoding="utf-8")
    monkeypatch.setenv("LLM_MATGEN_CONFIG", str(config))

    assert main(["cases", "scan", "--source", "demo", "--store-root", str(tmp_path / "store")]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["index_revision"] == 1


def test_cases_query_and_inspect_have_json_contract(tmp_path: Path, capsys):
    from llm_matgen.__main__ import main

    assert main(["cases", "query", "--store-root", str(tmp_path / "store")]) == 0
    assert json.loads(capsys.readouterr().out)["matches"] == []
    assert main(["cases", "inspect", "missing", "--store-root", str(tmp_path / "store")]) == 2
