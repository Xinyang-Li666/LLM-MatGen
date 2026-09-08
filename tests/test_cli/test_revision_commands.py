import json

from pymatgen.core import Lattice, Structure


def test_revision_import_cli_writes_audited_v2_artifact(tmp_path, monkeypatch, capsys):
    from llm_matgen.__main__ import main
    from llm_matgen.utils.structure import structure_sha256

    monkeypatch.chdir(tmp_path)
    parent = Structure(Lattice.cubic(4), ["Cu", "H"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    child = parent.copy()
    child.translate_sites([1], [0.01, 0, 0], frac_coords=True)
    parent.to(filename="parent.cif")
    child.to(filename="child.cif")
    sidecar = {
        "version": 2, "parent_hash": structure_sha256(parent), "child_hash": structure_sha256(child),
        "changes": [{"atom_index": 1, "old_frac_coords": parent.frac_coords[1].tolist(), "new_frac_coords": child.frac_coords[1].tolist()}],
    }
    (tmp_path / "revision.json").write_text(json.dumps(sidecar), encoding="utf-8")
    assert main(["revision", "import", "--parent", "parent.cif", "--child", "child.cif", "--sidecar", "revision.json", "--output-root", "revisions"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"] == 2
    assert (tmp_path / payload["path"]).is_dir() or __import__("pathlib").Path(payload["path"]).is_dir()
