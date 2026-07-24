import pytest
from pymatgen.core import Lattice, Structure


def silicon_structure() -> Structure:
    return Structure(
        Lattice.cubic(5.43),
        ["Si", "Si"],
        [[0, 0, 0], [0.25, 0.25, 0.25]],
    )


def test_surface_generates_slab_with_vacuum_without_mutating_input():
    from llm_matgen.generators.surface import SurfaceGenerator, SurfaceParams

    source = silicon_structure()
    original = source.copy()
    result = SurfaceGenerator().generate(
        source,
        SurfaceParams(
            miller_indices=[(0, 0, 1)],
            min_slab_size=6.0,
            min_vacuum_size=8.0,
        ),
    )
    assert result.generated_count >= 1
    slab = result.generated[0]
    assert slab.structure.lattice.c > 14.0
    assert slab.record.parent_structure_id == result.provenance.input_structure_hash
    assert slab.record.actual_parameters["miller_index"] == [0, 0, 1]
    assert source == original


def test_surface_normalizes_duplicate_miller_indices():
    from llm_matgen.generators.surface import SurfaceGenerator, SurfaceParams

    result = SurfaceGenerator().generate(
        silicon_structure(),
        SurfaceParams(
            miller_indices=[(0, 0, 1), (0, 0, 2)],
            min_slab_size=5.0,
            min_vacuum_size=5.0,
        ),
    )
    assert {tuple(item.record.actual_parameters["miller_index"]) for item in result.generated} == {(0, 0, 1)}


def test_surface_enforces_atom_limit():
    from llm_matgen.generators.surface import SurfaceGenerator, SurfaceParams

    with pytest.raises(ValueError, match="atom limit"):
        SurfaceGenerator().generate(
            silicon_structure(),
            SurfaceParams(
                miller_indices=[(0, 0, 1)],
                min_slab_size=20.0,
                min_vacuum_size=5.0,
                max_atoms_per_structure=1,
            ),
        )
