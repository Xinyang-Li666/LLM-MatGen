import json
from pathlib import Path

import pytest

from llm_matgen.trajectories.representative.models import SourceSpec
from llm_matgen.trajectories.representative.sources import (
    inventory_sources,
    iter_source_frames,
    load_source_config,
)


def _dump(type_id: int = 1, symbol: str | None = None) -> str:
    atom_line = (
        f"1 {type_id} 0 0 0\n"
        "2 2 2 0 0\n"
    )
    if symbol:
        return (
            "2\n"
            "Lattice=\"5 0 0 0 5 0 0 0 5\" Properties=species:S:1:pos:R:3\n"
            f"{symbol} 0 0 0\nB 2 0 0\n"
        )
    return (
        "ITEM: TIMESTEP\n0\nITEM: NUMBER OF ATOMS\n2\n"
        "ITEM: BOX BOUNDS pp pp pp\n0 5\n0 5\n0 5\n"
        "ITEM: ATOMS id type x y z\n" + atom_line
    )


def test_load_source_config_resolves_relative_paths_and_type_maps(tmp_path: Path):
    input_path = tmp_path / "input.dump"
    input_path.write_text(_dump(), encoding="utf-8")
    config_path = tmp_path / "sources.json"
    config_path.write_text(json.dumps({
        "sources": [{
            "name": "ALL_T",
            "path": "input.dump",
            "type_map": {"1": "Ti", "2": "B"},
            "cleaned": True,
        }],
        "allocation": "proportional",
    }), encoding="utf-8")

    sources = load_source_config(config_path)

    assert sources[0].path == input_path
    assert sources[0].type_map == {1: "Ti", 2: "B"}
    assert sources[0].cleaned is True


def test_inventory_streams_frames_and_records_hash_and_clean_warning(tmp_path: Path):
    input_path = tmp_path / "input.dump"
    input_path.write_text(_dump(), encoding="utf-8")
    source = SourceSpec(
        name="ALL_T", path=input_path, input_format="lammps-dump-text",
        type_map={1: "Ti", 2: "B"},
    )

    inventory = inventory_sources((source,))[0]
    frames = list(iter_source_frames(source))

    assert inventory.frame_count == 1
    assert inventory.atomic_numbers == (5, 22)
    assert inventory.natom_values == (2,)
    assert len(inventory.sha256) == 64
    assert inventory.warnings == ("input_not_declared_clean",)
    assert frames[0].source.name == "ALL_T"
    assert frames[0].frame.natoms == 2


def test_inventory_rejects_forbidden_and_unknown_elements(tmp_path: Path):
    carbon = tmp_path / "carbon.extxyz"
    carbon.write_text(_dump(symbol="C"), encoding="utf-8")
    source = SourceSpec(name="bad", path=carbon, input_format="extxyz")

    with pytest.raises(ValueError, match="forbidden element C"):
        inventory_sources((source,), forbidden_atomic_numbers={6, 7})

    with pytest.raises(ValueError, match="not allowed"):
        inventory_sources((source,), allowed_atomic_numbers={5, 22})


def test_inventory_rejects_missing_file_and_invalid_source_config(tmp_path: Path):
    missing = SourceSpec(name="missing", path=tmp_path / "missing.extxyz")
    with pytest.raises(FileNotFoundError):
        inventory_sources((missing,))

    config = tmp_path / "bad.json"
    config.write_text(json.dumps({"sources": [{"name": "", "path": "x"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="source name"):
        load_source_config(config)
