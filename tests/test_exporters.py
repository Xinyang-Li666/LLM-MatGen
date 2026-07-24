from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure


def make_fixture() -> Structure:
    return Structure(
        Lattice.cubic(4.2),
        ["Li", "Co", "O", "O"],
        [[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0.5, 0], [0.5, 0, 0.5]],
    )


def test_export_poscar_and_cif_round_trip(tmp_path: Path):
    from llm_matgen.generators.models import OutputFormat
    from llm_matgen.io.exporters import ExportOptions, StructureExporter
    from llm_matgen.io.readers import read_structure

    result = StructureExporter().export_structure(
        make_fixture(),
        "structure-00001",
        ExportOptions(
            formats=[OutputFormat.POSCAR, OutputFormat.CIF],
            output_dir=tmp_path,
        ),
    )

    assert {artifact.format for artifact in result.artifacts} == {
        OutputFormat.POSCAR,
        OutputFormat.CIF,
    }
    for artifact in result.artifacts:
        assert artifact.path.is_file()
        restored = read_structure(artifact.path, fmt=artifact.format.value)
        assert restored.num_sites == 4
        assert restored.composition == make_fixture().composition
        assert len(artifact.sha256) == 64


def test_export_does_not_overwrite_and_rejects_unsafe_ids(tmp_path: Path):
    from llm_matgen.generators.models import OutputFormat
    from llm_matgen.io.exporters import ExportOptions, StructureExporter

    exporter = StructureExporter()
    options = ExportOptions(formats=[OutputFormat.POSCAR], output_dir=tmp_path)
    first = exporter.export_structure(make_fixture(), "same-id", options)
    second = exporter.export_structure(make_fixture(), "same-id", options)

    assert first.artifacts[0].path != second.artifacts[0].path
    assert first.artifacts[0].path.read_bytes() == second.artifacts[0].path.read_bytes()

    with pytest.raises(ValueError, match="safe"):
        exporter.export_structure(make_fixture(), "../escape", options)


def test_export_lammps_data_has_type_map_and_masses(tmp_path: Path):
    from llm_matgen.generators.models import OutputFormat
    from llm_matgen.io.exporters import ExportOptions, StructureExporter
    from llm_matgen.io.readers import read_structure

    result = StructureExporter().export_structure(
        make_fixture(),
        "structure-00001",
        ExportOptions(
            formats=[OutputFormat.LAMMPS_DATA],
            output_dir=tmp_path,
            lammps_atom_style="charge",
        ),
    )

    artifact = result.artifacts[0]
    assert artifact.format is OutputFormat.LAMMPS_DATA
    assert artifact.metadata["atom_style"] == "charge"
    assert artifact.metadata["contains_force_field"] is False
    restored = read_structure(
        artifact.path,
        fmt="lammps-data",
        lammps_element_map={int(k): v for k, v in artifact.metadata["type_map"].items()},
    )
    assert restored.num_sites == make_fixture().num_sites
    assert restored.composition == make_fixture().composition


def test_export_lammps_rejects_unsupported_style_and_non_orthogonal_lattice(tmp_path: Path):
    from llm_matgen.generators.models import OutputFormat
    from llm_matgen.io.exporters import ExportOptions, StructureExporter

    exporter = StructureExporter()
    with pytest.raises(ValueError, match="atom style"):
        exporter.export_structure(
            make_fixture(),
            "bad-style",
            ExportOptions(
                formats=[OutputFormat.LAMMPS_DATA],
                output_dir=tmp_path,
                lammps_atom_style="full",
            ),
        )

    triclinic = Structure(
        Lattice.from_parameters(4, 4, 4, 80, 90, 90),
        ["Li"],
        [[0, 0, 0]],
    )
    with pytest.raises(ValueError, match="orthogonal"):
        exporter.export_structure(
            triclinic,
            "triclinic",
            ExportOptions(
                formats=[OutputFormat.LAMMPS_DATA],
                output_dir=tmp_path,
            ),
        )
