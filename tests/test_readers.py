from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure


def make_fixture() -> Structure:
    return Structure(
        Lattice.cubic(4.2),
        ["Li", "Co", "O", "O"],
        [[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0.5, 0], [0.5, 0, 0.5]],
    )


def test_read_poscar_and_cif_with_explicit_or_detected_format(tmp_path: Path):
    from llm_matgen.io.readers import read_structure

    source = make_fixture()
    poscar = tmp_path / "POSCAR"
    cif = tmp_path / "fixture.cif"
    source.to(filename=poscar, fmt="poscar")
    source.to(filename=cif, fmt="cif")

    assert read_structure(poscar).composition == source.composition
    assert read_structure(cif).composition == source.composition
    assert read_structure(poscar, fmt="poscar").num_sites == source.num_sites


def test_read_lammps_data_infers_atomic_numbers_without_mapping(tmp_path: Path):
    from llm_matgen.io.readers import read_structure

    data = tmp_path / "fixture.data"
    data.write_text(
        """2 atoms
2 atom types

0.0 4.2 xlo xhi
0.0 4.2 ylo yhi
0.0 4.2 zlo zhi

Masses

1 6.941
2 58.933

Atoms # charge

1 6 0.0 0.0 0.0 0.0
2 27 0.0 2.1 2.1 2.1
""",
        encoding="utf-8",
    )

    with pytest.warns(UserWarning, match="atomic-number") as caught:
        inferred = read_structure(data)
    assert len(caught) == 1
    assert inferred.composition.reduced_formula == "CoC"

    restored = read_structure(
        data,
        lammps_element_map={6: "Li", 27: "Co"},
    )
    assert restored.num_sites == 2
    assert restored.composition.reduced_formula == "LiCo"


def test_lammps_data_partial_mapping_prefers_explicit_values(tmp_path: Path):
    from llm_matgen.io.readers import read_structure

    data = tmp_path / "partial.data"
    data.write_text(
        """2 atoms
2 atom types

0.0 4.2 xlo xhi
0.0 4.2 ylo yhi
0.0 4.2 zlo zhi

Atoms # atomic

1 1 0.0 0.0 0.0
2 6 2.1 2.1 2.1
""",
        encoding="utf-8",
    )

    with pytest.warns(UserWarning, match="6=C"):
        restored = read_structure(data, lammps_element_map={1: "Fe"})
    assert restored.composition.reduced_formula == "FeC"


@pytest.mark.parametrize("type_id", [0, -1, 119])
def test_lammps_data_rejects_invalid_atomic_number_fallback(tmp_path: Path, type_id: int):
    from llm_matgen.io.readers import StructureReadError, read_structure

    data = tmp_path / f"invalid-{type_id}.data"
    data.write_text(
        f"""1 atoms
1 atom types
0.0 1.0 xlo xhi
0.0 1.0 ylo yhi
0.0 1.0 zlo zhi

Atoms # atomic

1 {type_id} 0.0 0.0 0.0
""",
        encoding="utf-8",
    )
    with pytest.raises(StructureReadError, match="atomic number"):
        read_structure(data)


def test_readers_reject_unknown_extension_and_corrupt_content(tmp_path: Path):
    from llm_matgen.io.readers import StructureReadError, read_structure

    unknown = tmp_path / "structure.xyz"
    unknown.write_text("not supported", encoding="utf-8")
    with pytest.raises(StructureReadError, match="format"):
        read_structure(unknown)

    corrupt = tmp_path / "POSCAR"
    corrupt.write_text("broken", encoding="utf-8")
    with pytest.raises(StructureReadError):
        read_structure(corrupt)

    missing = tmp_path / "missing.cif"
    with pytest.raises(StructureReadError, match="does not exist"):
        read_structure(missing)


def test_lammps_reader_reports_header_style_mapping_and_box_errors(tmp_path: Path):
    from llm_matgen.io.readers import StructureReadError, read_structure

    malformed = tmp_path / "bad.data"
    malformed.write_text("2 atoms\nAtoms\n", encoding="utf-8")
    with pytest.raises(StructureReadError, match="headers"):
        read_structure(malformed, lammps_element_map={1: "Li"})

    unsupported = tmp_path / "style.data"
    unsupported.write_text(
        """1 atoms
1 atom types
0 1 xlo xhi
0 1 ylo yhi
0 1 zlo zhi
Atoms # full
1 1 0 0 0 0 0
""",
        encoding="utf-8",
    )
    with pytest.raises(StructureReadError, match="atom style"):
        read_structure(unsupported, lammps_element_map={1: "Li"})

    missing_type = tmp_path / "missing-type.data"
    missing_type.write_text(
        """1 atoms
1 atom types
0 1 xlo xhi
0 1 ylo yhi
0 1 zlo zhi
Atoms # charge
1 2 0 0 0 0
""",
        encoding="utf-8",
    )
    with pytest.warns(UserWarning, match="2=He"):
        restored = read_structure(missing_type, lammps_element_map={1: "Li"})
    assert restored.composition.reduced_formula == "He"
