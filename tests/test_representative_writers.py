from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from ase.io import read

from llm_matgen.trajectories.filtering.models import FilterFrame
from llm_matgen.trajectories.representative.models import SelectionRecord
from llm_matgen.trajectories.representative.writers import write_outputs


def test_writes_auditable_extxyz_and_optional_formats(tmp_path: Path):
    frame = FilterFrame(np.array([22, 5]), np.array([[0, 0, 0], [1, 0, 0.]]), np.diag([4., 4., 4.]), np.array([True] * 3), timestep=17)
    record = SelectionRecord("源一", 3, 17, 0, None, 1)
    result = write_outputs([(frame, record)], tmp_path / "输出", formats=("poscar", "cif", "lammps"))
    selected = Path(result["selected_path"])
    atoms = read(selected, index=0)
    assert len(atoms) == 2
    rows = [json.loads(line) for line in Path(result["selection_path"]).read_text(encoding="utf-8").splitlines()]
    assert rows[0]["source_name"] == "源一" and rows[0]["source_index"] == 3
    assert Path(result["summary_path"]).read_text(encoding="utf-8")
    assert Path(result["manifest_path"]).read_text(encoding="utf-8")
    assert (selected.parent / "poscar" / "000000.vasp").exists()
    assert (selected.parent / "cif" / "000000.cif").exists()
    assert (selected.parent / "lammps" / "000000.data").exists()


def test_runs_do_not_overwrite_and_cache_reference_is_relative(tmp_path: Path):
    frame = FilterFrame(np.array([5]), np.array([[0, 0, 0.]]), np.diag([3., 3., 3.]), np.array([True] * 3))
    record = SelectionRecord("s", 0, None, 0, None, 1)
    first = write_outputs([(frame, record)], tmp_path / "out", cache_root=tmp_path / "cache")
    second = write_outputs([(frame, record)], tmp_path / "out", cache_root=tmp_path / "cache")
    assert first["run_dir"] != second["run_dir"]
    ref = json.loads((Path(first["run_dir"]) / "cache-reference.json").read_text(encoding="utf-8"))
    assert not Path(ref["cache_root"]).is_absolute()
