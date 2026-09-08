def test_package_exposes_version():
    import llm_matgen

    assert llm_matgen.__version__ == "0.2.0rc1"


def test_public_subpackages_export_core_types():
    from llm_matgen.checks import CheckReport, LightStructureChecker
    from llm_matgen.generators import GenerationResult, OutputFormat
    from llm_matgen.io import ExportOptions, StructureExporter

    assert OutputFormat.POSCAR.value == "poscar"
    assert GenerationResult(defect_type="test").generated_count == 0
    assert CheckReport(n_atoms=0, formula="").can_export is True
    assert LightStructureChecker is not None
    assert ExportOptions().formats
    assert StructureExporter is not None


def test_trajectory_package_exports_runtime_contracts():
    from llm_matgen.trajectories import (
        FilterConfig,
        FilterResult,
        SamplingMethod,
        TrajectoryFrame,
        filter_trajectory,
        random_indices,
        uniform_indices,
    )

    assert FilterConfig().dimensions
    assert FilterResult is not None
    assert SamplingMethod.UNIFORM.value == "uniform"
    assert TrajectoryFrame is not None
    assert filter_trajectory is not None
    assert random_indices(3, 2, seed=1) == [0, 2]
    assert uniform_indices(3, 2) == [0, 2]
