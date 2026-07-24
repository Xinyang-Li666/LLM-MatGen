import numpy as np
import pytest


def test_edge_displacement_matches_hand_calculated_point():
    from llm_matgen.generators.dislocation import isotropic_displacement_field

    displacement = isotropic_displacement_field(
        np.array([[1.0, 0.0, 0.0]]),
        burgers_vector=(1.0, 0.0, 0.0),
        character="edge",
        poisson_ratio=0.3,
    )[0]
    expected_y = -(1 / (2 * np.pi)) * (1 / (4 * (1 - 0.3)))
    assert np.allclose(displacement, [0.0, expected_y, 0.0])


def test_screw_displacement_matches_quarter_turn():
    from llm_matgen.generators.dislocation import isotropic_displacement_field

    displacement = isotropic_displacement_field(
        np.array([[1.0, 1.0, 0.0]]),
        burgers_vector=(0.0, 0.0, 1.0),
        character="screw",
        poisson_ratio=0.3,
    )[0]
    assert np.allclose(displacement, [0.0, 0.0, 0.125])


def test_displacement_field_is_finite_at_core_and_rejects_invalid_inputs():
    from llm_matgen.generators.dislocation import isotropic_displacement_field

    value = isotropic_displacement_field(
        np.zeros((1, 3)),
        burgers_vector=(1.0, 0.0, 0.0),
        character="edge",
        poisson_ratio=0.3,
        core_cutoff=0.1,
    )
    assert np.isfinite(value).all()
    with pytest.raises(ValueError, match="Burgers"):
        isotropic_displacement_field(np.zeros((1, 3)), (0, 0, 0), "edge", 0.3)
    with pytest.raises(ValueError, match="Poisson"):
        isotropic_displacement_field(np.zeros((1, 3)), (1, 0, 0), "edge", 0.5)
