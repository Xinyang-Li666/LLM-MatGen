import numpy as np
import pytest
from pydantic import ValidationError
from pymatgen.core import Lattice, Structure

from llm_matgen.generators.models import OutputFormat
from llm_matgen.io.exporters import ExportOptions
from llm_matgen.pipeline import GenerationPipeline


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


def fixture_structure() -> Structure:
    return Structure(Lattice.cubic(4.0), ["Al"], [[0, 0, 0]])


def make_params(**updates):
    from llm_matgen.generators.dislocation import DislocationParams

    values = dict(
        line_direction=(0, 0, 1),
        burgers_vector=(0.0, 0.0, 1.0),
        slip_plane=(1, 0, 0),
        character="screw",
        core_position=(0.5, 0.5),
        radius=5.0,
        poisson_ratio=0.3,
    )
    values.update(updates)
    return DislocationParams(**values)


def test_dislocation_generator_builds_and_displaces_cylindrical_supercell():
    from llm_matgen.generators.dislocation import DislocationGenerator

    source = fixture_structure()
    result = DislocationGenerator().generate(source, make_params())
    child = result.generated[0]
    assert child.structure.num_sites > source.num_sites
    assert child.record.actual_parameters["character"] == "screw"
    assert child.record.actual_parameters["boundary_conditions"] == ["non-periodic", "non-periodic", "periodic"]
    assert np.isfinite(child.structure.cart_coords).all()


def test_dislocation_params_reject_character_mismatch():
    with pytest.raises(ValidationError, match="screw"):
        make_params(burgers_vector=(1.0, 0.0, 0.0))


def test_dislocation_pipeline_exports_all_formats(tmp_path):
    from llm_matgen.generators.dislocation import DislocationGenerator

    result = GenerationPipeline(tmp_path).run(
        DislocationGenerator(),
        fixture_structure(),
        make_params(),
        ExportOptions(formats=list(OutputFormat)),
        run_id="dislocation",
    )
    assert result.ok
    assert {artifact.format for artifact in result.artifacts} == set(OutputFormat)


def test_dislocation_is_public_generator_api():
    from llm_matgen.generators import DislocationGenerator, DislocationParams

    assert DislocationGenerator is not None
    assert DislocationParams is not None
