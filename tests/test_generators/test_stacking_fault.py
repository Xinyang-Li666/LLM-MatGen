import numpy as np
import pytest
from pydantic import ValidationError
from pymatgen.core import Lattice, Structure

from llm_matgen.generators.models import OutputFormat
from llm_matgen.io.exporters import ExportOptions
from llm_matgen.pipeline import GenerationPipeline


def fixture_structure() -> Structure:
    return Structure(
        Lattice.cubic(4.0),
        ["Al", "Al"],
        [[0.25, 0.25, 0.25], [0.25, 0.25, 0.75]],
    )


def test_stacking_fault_moves_only_sites_above_fault_plane():
    from llm_matgen.generators.stacking_fault import StackingFaultGenerator, StackingFaultParams

    source = fixture_structure()
    original = source.copy()
    result = StackingFaultGenerator().generate(
        source,
        StackingFaultParams(
            plane=(0, 0, 2),
            slip_vector=(0.1, 0.0, 0.0),
            fault_position=0.5,
        ),
    )
    child = result.generated[0].structure
    assert np.allclose(child.frac_coords[0], [0.25, 0.25, 0.25])
    assert np.allclose(child.frac_coords[1], [0.35, 0.25, 0.75])
    assert result.generated[0].record.actual_parameters["plane"] == [0, 0, 1]
    assert source == original


def test_stacking_fault_rejects_zero_slip():
    from llm_matgen.generators.stacking_fault import StackingFaultParams

    with pytest.raises(ValidationError, match="slip"):
        StackingFaultParams(plane=(0, 0, 1), slip_vector=(0, 0, 0))


def test_stacking_fault_pipeline_exports_all_formats(tmp_path):
    from llm_matgen.generators.stacking_fault import StackingFaultGenerator, StackingFaultParams

    result = GenerationPipeline(tmp_path).run(
        StackingFaultGenerator(),
        fixture_structure(),
        StackingFaultParams(plane=(0, 0, 1), slip_vector=(0.1, 0, 0)),
        ExportOptions(formats=list(OutputFormat)),
        run_id="stacking-fault",
    )
    assert result.ok
    assert {artifact.format for artifact in result.artifacts} == set(OutputFormat)


def test_stacking_fault_is_public_generator_api():
    from llm_matgen.generators import StackingFaultGenerator, StackingFaultParams

    assert StackingFaultGenerator is not None
    assert StackingFaultParams is not None
