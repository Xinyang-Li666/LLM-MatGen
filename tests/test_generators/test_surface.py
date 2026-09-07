import pytest
from pymatgen.core import Lattice, Structure
from llm_matgen.generators.models import OutputFormat
from llm_matgen.io.exporters import ExportOptions
from llm_matgen.pipeline import GenerationPipeline


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


def test_surface_deduplicates_symmetry_equivalent_cubic_planes():
    from llm_matgen.generators.surface import SurfaceGenerator, SurfaceParams

    result = SurfaceGenerator().generate(
        silicon_structure(),
        SurfaceParams(
            miller_indices=[(1, 0, 0), (0, 1, 0)],
            min_slab_size=5.0,
            min_vacuum_size=5.0,
        ),
    )
    assert result.generated_count == 1
    assert any("duplicate" in warning for warning in result.warnings)


def test_surface_pipeline_exports_all_formats(tmp_path):
    from llm_matgen.generators.surface import SurfaceGenerator, SurfaceParams

    result = GenerationPipeline(tmp_path).run(
        SurfaceGenerator(),
        silicon_structure(),
        SurfaceParams(
            miller_indices=[(0, 0, 1)],
            min_slab_size=5.0,
            min_vacuum_size=5.0,
        ),
        ExportOptions(formats=list(OutputFormat)),
        run_id="surface",
    )
    assert result.ok
    assert {artifact.format for artifact in result.artifacts} == set(OutputFormat)


def test_surface_is_public_generator_api():
    from llm_matgen.generators import SurfaceGenerator, SurfaceParams

    assert SurfaceGenerator is not None
    assert SurfaceParams is not None


def test_surface_cell_shape_defaults_preserve_native_mode():
    from llm_matgen.generators.surface import SurfaceParams

    params = SurfaceParams(
        miller_indices=[(0, 0, 1)],
        min_slab_size=5.0,
        min_vacuum_size=8.0,
    )

    assert params.cell_shape == "native"
    assert params.orthogonal_max_area == 8
    assert params.orthogonal_tolerance == 0.1


@pytest.mark.parametrize(
    "overrides",
    [
        {"cell_shape": "cubic"},
        {"orthogonal_max_area": 0},
        {"orthogonal_tolerance": 0},
    ],
)
def test_surface_rejects_invalid_orthogonal_options(overrides):
    from pydantic import ValidationError
    from llm_matgen.generators.surface import SurfaceParams

    with pytest.raises(ValidationError):
        SurfaceParams(
            miller_indices=[(0, 0, 1)],
            min_slab_size=5.0,
            min_vacuum_size=8.0,
            **overrides,
        )


def test_surface_near_orthogonal_records_cell_diagnostics():
    from llm_matgen.generators.surface import SurfaceGenerator, SurfaceParams

    result = SurfaceGenerator().generate(
        silicon_structure(),
        SurfaceParams(
            miller_indices=[(0, 0, 1)],
            min_slab_size=6.0,
            min_vacuum_size=8.0,
            cell_shape="near-orthogonal",
        ),
    )

    record = result.generated[0].record.actual_parameters
    assert record["cell_shape_requested"] == "near-orthogonal"
    assert record["cell_shape_status"] == "strict"
    assert record["area_multiplier"] == 1
    assert record["inplane_transform"] == [[1, 0], [0, 1]]
    assert all(abs(angle - 90.0) <= 0.1 for angle in record["lattice_angles"])
    assert record["material_span"] >= 0
    assert record["vacuum_estimate"] >= 0


def test_surface_native_explicit_and_implicit_outputs_match():
    from llm_matgen.generators.surface import SurfaceGenerator, SurfaceParams

    common = dict(miller_indices=[(0, 0, 1)], min_slab_size=6.0, min_vacuum_size=8.0)
    implicit = SurfaceGenerator().generate(silicon_structure(), SurfaceParams(**common))
    explicit = SurfaceGenerator().generate(
        silicon_structure(), SurfaceParams(**common, cell_shape="native")
    )

    assert implicit.generated[0].record.structure_id == explicit.generated[0].record.structure_id
    assert implicit.generated[0].structure == explicit.generated[0].structure


def test_surface_near_orthogonal_keeps_other_termination_when_one_exceeds_limit(monkeypatch):
    from llm_matgen.generators.surface import SurfaceGenerator, SurfaceParams

    generator = SurfaceGenerator()
    original = generator._shape_surface_cell
    calls = {"count": 0}

    def shaped(slab, params):
        calls["count"] += 1
        return original(slab, params)

    monkeypatch.setattr(generator, "_shape_surface_cell", shaped)
    result = generator.generate(
        silicon_structure(),
        SurfaceParams(
            miller_indices=[(0, 0, 1)],
            min_slab_size=6.0,
            min_vacuum_size=8.0,
            cell_shape="near-orthogonal",
            max_atoms_per_structure=100,
        ),
    )

    assert calls["count"] >= 1
    assert result.generated_count == 1


def test_surface_c_orthogonalization_failure_falls_back_to_native(monkeypatch):
    import llm_matgen.generators.surface as surface_module
    from llm_matgen.generators.surface import SurfaceGenerator, SurfaceParams

    def fail(_slab):
        raise RuntimeError("missing pymatgen capability")

    monkeypatch.setattr(surface_module, "orthogonalize_c_axis", fail)
    result = SurfaceGenerator().generate(
        silicon_structure(),
        SurfaceParams(
            miller_indices=[(0, 0, 1)],
            min_slab_size=6.0,
            min_vacuum_size=8.0,
            cell_shape="near-orthogonal",
        ),
    )

    assert result.generated[0].record.actual_parameters["cell_shape_status"] == "fallback-native"
    assert any("orthogonalization unavailable" in warning for warning in result.warnings)


def test_surface_inplane_search_failure_falls_back_to_c_orthogonal(monkeypatch):
    import llm_matgen.generators.surface as surface_module
    from llm_matgen.generators.surface import SurfaceGenerator, SurfaceParams

    def fail(*args, **kwargs):
        raise RuntimeError("search failed")

    monkeypatch.setattr(surface_module, "find_inplane_transform", fail)
    result = SurfaceGenerator().generate(
        silicon_structure(),
        SurfaceParams(
            miller_indices=[(0, 0, 1)],
            min_slab_size=6.0,
            min_vacuum_size=8.0,
            cell_shape="near-orthogonal",
        ),
    )

    assert result.generated[0].record.actual_parameters["cell_shape_status"] == "fallback-c-orthogonal"
    assert any("integer search unavailable" in warning for warning in result.warnings)


def test_surface_approximate_transform_is_kept_with_warning(monkeypatch):
    import llm_matgen.generators.surface as surface_module
    from llm_matgen.generators.surface import SurfaceGenerator, SurfaceParams
    from llm_matgen.generators.surface_cell import InplaneTransform

    approximate = InplaneTransform(
        matrix=((1, 0), (0, 1)),
        lattice_angles=(90.0, 90.0, 60.0),
        area_multiplier=1,
        inplane_aspect_ratio=1.0,
        total_angle_error=30.0,
        strict=False,
    )
    monkeypatch.setattr(surface_module, "find_inplane_transform", lambda *args, **kwargs: approximate)
    result = SurfaceGenerator().generate(
        silicon_structure(),
        SurfaceParams(
            miller_indices=[(0, 0, 1)],
            min_slab_size=6.0,
            min_vacuum_size=8.0,
            cell_shape="near-orthogonal",
        ),
    )

    assert result.generated[0].record.actual_parameters["cell_shape_status"] == "approximate"
    assert any("approximate" in warning for warning in result.warnings)
