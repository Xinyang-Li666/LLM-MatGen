import numpy as np
import pytest
from pymatgen.core import Lattice, Structure
from pymatgen.core.surface import SlabGenerator


def fcc_al_structure() -> Structure:
    return Structure(
        Lattice.cubic(4.05),
        ["Al"] * 4,
        [
            [0.0, 0.0, 0.0],
            [0.0, 0.5, 0.5],
            [0.5, 0.0, 0.5],
            [0.5, 0.5, 0.0],
        ],
    )


def make_slab(miller=(1, 1, 1), *, slab_size=12.0, vacuum=12.0, primitive=True):
    return list(
        SlabGenerator(
            fcc_al_structure(),
            miller,
            min_slab_size=slab_size,
            min_vacuum_size=vacuum,
            lll_reduce=False,
            center_slab=True,
            primitive=primitive,
        ).get_slabs()
    )[0]


def test_fcc_111_transform_is_strict_area_two():
    from llm_matgen.generators.surface_cell import (
        find_inplane_transform,
        orthogonalize_c_axis,
    )

    slab = orthogonalize_c_axis(make_slab())
    transform = find_inplane_transform(slab, max_area=8, tolerance=0.1)

    assert transform.strict is True
    assert transform.area_multiplier == 2
    assert all(abs(angle - 90.0) <= 0.1 for angle in transform.lattice_angles)


def test_already_orthogonal_surface_prefers_identity():
    from llm_matgen.generators.surface_cell import (
        find_inplane_transform,
        orthogonalize_c_axis,
    )

    slab = orthogonalize_c_axis(make_slab((0, 0, 1), primitive=False))
    transform = find_inplane_transform(slab, max_area=8, tolerance=0.1)

    assert transform.matrix == ((1, 0), (0, 1))
    assert transform.area_multiplier == 1


def test_transform_is_integer_positive_and_bounded():
    from llm_matgen.generators.surface_cell import (
        find_inplane_transform,
        orthogonalize_c_axis,
    )

    transform = find_inplane_transform(
        orthogonalize_c_axis(make_slab()), max_area=4, tolerance=0.1
    )
    values = tuple(value for row in transform.matrix for value in row)

    assert all(isinstance(value, int) for value in values)
    assert transform.area_multiplier == (
        transform.matrix[0][0] * transform.matrix[1][1]
        - transform.matrix[0][1] * transform.matrix[1][0]
    )
    assert 1 <= transform.area_multiplier <= 4


def test_apply_transform_scales_atoms_and_preserves_composition():
    from llm_matgen.generators.surface_cell import (
        apply_inplane_transform,
        find_inplane_transform,
        orthogonalize_c_axis,
    )

    slab = orthogonalize_c_axis(make_slab())
    transform = find_inplane_transform(slab, max_area=8, tolerance=0.1)
    shaped = apply_inplane_transform(slab, transform)

    assert len(shaped) == len(slab) * transform.area_multiplier
    for element, amount in slab.composition.items():
        assert shaped.composition[element] == amount * transform.area_multiplier
    assert np.allclose(shaped.lattice.matrix[2], slab.lattice.matrix[2])


def test_search_is_deterministic():
    from llm_matgen.generators.surface_cell import (
        find_inplane_transform,
        orthogonalize_c_axis,
    )

    slab = orthogonalize_c_axis(make_slab())
    first = find_inplane_transform(slab, max_area=8, tolerance=0.1)
    second = find_inplane_transform(slab, max_area=8, tolerance=0.1)

    assert first == second


def test_no_strict_candidate_returns_best_approximation():
    from llm_matgen.generators.surface_cell import (
        find_inplane_transform,
        orthogonalize_c_axis,
    )

    transform = find_inplane_transform(
        orthogonalize_c_axis(make_slab()), max_area=1, tolerance=0.1
    )

    assert transform.strict is False
    assert transform.matrix == ((1, 0), (0, 1))


def test_zero_length_lattice_vector_is_rejected():
    from llm_matgen.generators.surface_cell import lattice_angle

    with pytest.raises(ValueError, match="finite non-zero"):
        lattice_angle(np.zeros(3), np.ones(3))
