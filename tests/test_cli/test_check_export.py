import json
from pathlib import Path

from pymatgen.core import Lattice, Structure
from pymatgen.io.cif import CifWriter


def write_close_contact_cif(path: Path):
    structure = Structure(Lattice.cubic(4), ["H", "H"], [[0, 0, 0], [0.01, 0, 0]])
    CifWriter(structure).write_file(path)


def test_check_warning_exits_zero(tmp_path: Path, monkeypatch, capsys):
    from llm_matgen.__main__ import main

    monkeypatch.chdir(tmp_path)
    write_close_contact_cif(tmp_path / "input.cif")
    assert main(["check", "input.cif"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["files"][0]["warnings"] > 0


def test_check_structural_error_exits_partial(tmp_path: Path, monkeypatch):
    from llm_matgen.__main__ import main
    import llm_matgen.io.readers as readers

    monkeypatch.chdir(tmp_path)
    (tmp_path / "input.cif").write_text("placeholder", encoding="utf-8")
    empty = Structure(Lattice.cubic(4), [], [])
    monkeypatch.setattr(readers, "read_structure", lambda *args, **kwargs: empty)
    assert main(["check", "input.cif"]) == 3


def test_export_cli_writes_multiple_formats_and_manifest(tmp_path: Path, monkeypatch, capsys):
    from llm_matgen.__main__ import main

    monkeypatch.chdir(tmp_path)
    CifWriter(Structure(Lattice.cubic(4), ["Si"], [[0, 0, 0]])).write_file("input.cif")
    code = main([
        "export", "input.cif", "--format", "poscar", "--format", "cif",
        "--format", "lammps-data", "--output-root", "exports",
    ])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    manifest_path = Path(payload["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert {item["format"] for item in manifest["artifacts"]} == {"poscar", "cif", "lammps-data"}
    assert manifest["parameters"]["source_hashes"]
