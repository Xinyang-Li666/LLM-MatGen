import numpy as np
from pymatgen.core import Lattice, Structure


def fixture_structure() -> Structure:
    return Structure(
        Lattice.cubic(4.2),
        ["Li", "Co", "O", "O"],
        [[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0.5, 0], [0.5, 0, 0.5]],
    )


def test_interstitial_candidates_respect_minimum_distance():
    from llm_matgen.generators.interstitial import find_voronoi_candidates

    structure = fixture_structure()
    candidates = find_voronoi_candidates(structure, min_distance=0.8)
    assert candidates
    for candidate in candidates:
        assert np.isfinite(candidate).all()
        for site in structure:
            distance, _ = structure.lattice.get_distance_and_image(
                site.frac_coords,
                candidate,
            )
            assert distance >= 0.8


def test_interstitial_generation_inserts_element_and_records_new_site():
    from llm_matgen.generators.interstitial import (
        InterstitialGenerator,
        InterstitialParams,
    )

    result = InterstitialGenerator().generate(
        fixture_structure(),
        InterstitialParams(
            elements=["H"],
            counts=[1],
            candidate_mode="random",
            min_distance=0.8,
            seed=7,
        ),
    )

    assert result.generated_count == 1
    child = result.generated[0]
    assert child.structure.composition["H"] == 1
    assert any(value is None for value in child.record.site_mapping.values())


def test_interstitial_candidate_exhaustion_is_reported_without_hanging():
    from llm_matgen.generators.interstitial import (
        InterstitialGenerator,
        InterstitialParams,
    )

    result = InterstitialGenerator().generate(
        fixture_structure(),
        InterstitialParams(
            elements=["H"],
            counts=[10],
            candidate_mode="random",
            min_distance=10,
            max_attempts=2,
            seed=7,
        ),
    )

    assert result.generated_count == 0
    assert any("candidate" in warning for warning in result.warnings)


def test_random_candidates_respect_pairwise_distance_for_triclinic_cell():
    from llm_matgen.generators.interstitial import _find_random_candidates

    structure = Structure(
        Lattice.from_parameters(3.1, 5.2, 7.4, 74, 83, 68),
        ["Si"],
        [[0, 0, 0]],
    )
    candidates = _find_random_candidates(
        structure,
        min_distance=1.0,
        max_attempts=80,
        rng=np.random.default_rng(0),
    )
    for index, first in enumerate(candidates):
        for second in candidates[index + 1:]:
            distance, _ = structure.lattice.get_distance_and_image(first, second)
            assert distance >= 1.0
