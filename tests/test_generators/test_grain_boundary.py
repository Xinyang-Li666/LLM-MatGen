from pymatgen.core import Lattice, Structure

from llm_matgen.generators.backends import BackendStructure
from llm_matgen.generators.models import OutputFormat
from llm_matgen.io.exporters import ExportOptions
from llm_matgen.pipeline import GenerationPipeline


def fixture_structure() -> Structure:
    return Structure(Lattice.cubic(3.6), ["Cu", "Cu"], [[0, 0, 0], [0.5, 0.5, 0.5]])


class FakeBackend:
    def __init__(self):
        self.angles = []

    def generate(self, structure, **kwargs):
        self.angles.append(kwargs["rotation_angle"])
        child = structure.copy()
        child.translate_sites([1], [kwargs["rotation_angle"] / 360, 0, 0], frac_coords=True)
        return BackendStructure(child, dict(kwargs))


def test_grain_boundary_generates_multiple_angles_with_provenance():
    from llm_matgen.generators.grain_boundary import GrainBoundaryGenerator, GrainBoundaryParams

    backend = FakeBackend()
    source = fixture_structure()
    original = source.copy()
    result = GrainBoundaryGenerator(backend=backend).generate(
        source,
        GrainBoundaryParams(
            rotation_axis=(0, 0, 2),
            rotation_angles=[15.0, 30.0],
            plane=(2, 0, 0),
            expand_times=2,
        ),
    )
    assert result.generated_count == 2
    assert backend.angles == [15.0, 30.0]
    assert result.generated[0].record.actual_parameters["rotation_axis"] == [0, 0, 1]
    assert result.generated[0].record.actual_parameters["plane"] == [1, 0, 0]
    assert source == original


def test_grain_boundary_enforces_atom_limit():
    import pytest
    from llm_matgen.generators.grain_boundary import GrainBoundaryGenerator, GrainBoundaryParams

    with pytest.raises(ValueError, match="atom limit"):
        GrainBoundaryGenerator(backend=FakeBackend()).generate(
            fixture_structure(),
            GrainBoundaryParams(
                rotation_axis=(0, 0, 1),
                rotation_angles=[15.0],
                max_atoms_per_structure=1,
            ),
        )


def test_grain_boundary_pipeline_exports_all_formats(tmp_path):
    from llm_matgen.generators.grain_boundary import GrainBoundaryGenerator, GrainBoundaryParams

    result = GenerationPipeline(tmp_path).run(
        GrainBoundaryGenerator(backend=FakeBackend()),
        fixture_structure(),
        GrainBoundaryParams(rotation_axis=(0, 0, 1), rotation_angles=[15.0]),
        ExportOptions(formats=list(OutputFormat)),
        run_id="grain-boundary",
    )
    assert result.ok
    assert {artifact.format for artifact in result.artifacts} == set(OutputFormat)


def test_grain_boundary_is_public_generator_api():
    from llm_matgen.generators import GrainBoundaryGenerator, GrainBoundaryParams

    assert GrainBoundaryGenerator is not None
    assert GrainBoundaryParams is not None
