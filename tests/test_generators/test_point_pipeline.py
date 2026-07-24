from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure

from llm_matgen.generators.doping import DopingGenerator, DopingParams
from llm_matgen.generators.interstitial import InterstitialGenerator, InterstitialParams
from llm_matgen.generators.solid_solution import SolidSolutionGenerator, SolidSolutionParams
from llm_matgen.generators.vacancy import VacancyGenerator, VacancyParams
from llm_matgen.io.exporters import ExportOptions
from llm_matgen.generators.models import OutputFormat
from llm_matgen.pipeline import GenerationPipeline


def fixture_structure() -> Structure:
    return Structure(
        Lattice.cubic(4.2),
        ["Co", "Co", "O", "O"],
        [[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0.5, 0], [0.5, 0, 0.5]],
    )


@pytest.mark.parametrize(
    "name,generator,params",
    [
        ("vacancy", VacancyGenerator(), VacancyParams(target_elements=["Co"], counts=[1], seed=7)),
        ("interstitial", InterstitialGenerator(), InterstitialParams(elements=["H"], counts=[1], seed=7)),
        ("doping", DopingGenerator(), DopingParams(dopant_elements=["Ni"], target_elements=["Co"], dopant_counts=[1], seed=7)),
        ("solid", SolidSolutionGenerator(), SolidSolutionParams(target_element="Co", substituents={"Ni": 1.0}, seed=7)),
    ],
)
def test_point_generators_run_through_pipeline(tmp_path: Path, name, generator, params):
    result = GenerationPipeline(tmp_path).run(
        generator,
        fixture_structure(),
        params,
        ExportOptions(formats=[OutputFormat.POSCAR, OutputFormat.CIF, OutputFormat.LAMMPS_DATA]),
        run_id=f"run-{name}",
    )
    assert result.ok
    assert len(result.generation.generated) == 1
    assert {artifact.format for artifact in result.artifacts} == set(OutputFormat)
    assert result.manifest_path.exists()
