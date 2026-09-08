import hashlib
import json
import re

import numpy as np
import pytest
from pymatgen.core import Lattice, Structure


def _structure():
    return Structure(
        Lattice.cubic(4),
        ["Si", "Si"],
        [[0, 0, 0], [0.25, 0.25, 0.25]],
        site_properties={"selective_dynamics": [[False] * 3, [True] * 3]},
    )


def test_structure_payload_is_ordered_finite_bounded_and_preserves_input(monkeypatch):
    import llm_matgen.viewer as viewer

    structure = _structure()
    before = structure.as_dict()
    payload = viewer.structure_payload("candidate", structure)
    assert payload["atoms"][1]["position"] == [1.0, 1.0, 1.0]
    assert payload["atoms"][0]["fixed"] is True
    assert payload["atoms"][1]["fixed"] is False
    assert structure.as_dict() == before

    monkeypatch.setattr(viewer, "MAX_ATOMS_PER_STRUCTURE", 1)
    with pytest.raises(ValueError, match="最多"):
        viewer.structure_payload("candidate", structure)


def test_structure_payload_rejects_empty_disordered_nonfinite_and_dense(monkeypatch):
    import llm_matgen.viewer as viewer

    with pytest.raises(ValueError, match="非空"):
        viewer.structure_payload("empty", Structure(Lattice.cubic(4), [], []))
    disordered = Structure(Lattice.cubic(4), [{"Si": 0.5, "Ge": 0.5}], [[0, 0, 0]])
    with pytest.raises(ValueError, match="有序"):
        viewer.structure_payload("disordered", disordered)
    nonfinite = _structure()
    nonfinite.translate_sites([0], [float("nan"), 0, 0], frac_coords=False)
    with pytest.raises(ValueError, match="有效"):
        viewer.structure_payload("nan", nonfinite)
    monkeypatch.setattr(viewer, "MAX_NEIGHBORS_PER_ATOM", 1)
    dense = Structure(Lattice.cubic(4), ["H", "H", "H"], [[0, 0, 0], [0.05, 0, 0], [0.1, 0, 0]], coords_are_cartesian=True)
    with pytest.raises(ValueError, match="过于密集"):
        viewer.structure_payload("dense", dense)


def test_write_viewer_is_offline_escaped_atomic_and_hash_addressed(tmp_path):
    from llm_matgen.viewer import write_viewer

    label = "</script><script>alert(1)</script>"
    artifact = write_viewer([(label, _structure())], tmp_path / "viewer.html")
    text = artifact.path.read_text(encoding="utf-8")
    match = re.search(r'<script id="structure-data" type="application/json">(.*?)</script>', text, re.S)
    payload = json.loads(match.group(1))
    assert payload["entries"][0]["label"] == label
    assert label not in text
    assert not re.search(r'<script[^>]+src=', text)
    assert hashlib.sha256(artifact.path.read_bytes()).hexdigest() == artifact.sha256
    assert not list(tmp_path.glob("*.tmp"))


def test_write_viewer_limits_labels_total_atoms_and_serialized_bytes(tmp_path, monkeypatch):
    import llm_matgen.viewer as viewer

    with pytest.raises(ValueError, match="标签"):
        viewer.write_viewer([("x" * (viewer.MAX_LABEL_LENGTH + 1), _structure())], tmp_path / "viewer.html")
    monkeypatch.setattr(viewer, "MAX_TOTAL_ATOMS", 1)
    with pytest.raises(ValueError, match="总原子数"):
        viewer.write_viewer([("candidate", _structure())], tmp_path / "viewer.html")
    monkeypatch.setattr(viewer, "MAX_TOTAL_ATOMS", 10)
    monkeypatch.setattr(viewer, "MAX_SERIALIZED_BYTES", 10)
    with pytest.raises(ValueError, match="页面数据"):
        viewer.write_viewer([("candidate", _structure())], tmp_path / "viewer.html")


def test_pinned_renderer_and_license_are_packaged():
    from llm_matgen.viewer import renderer_metadata

    metadata = renderer_metadata()
    assert metadata["version"] == "2.0.4"
    assert metadata["sha256"] == "612eedd3ad7c36537813066d04f15a6e71285b9c59b364a6ab0296e39c67b7d1"
    assert metadata["upstream"] == "https://github.com/3dmol/3Dmol.js"
    assert "BSD-3-Clause" in metadata["license_text"]
