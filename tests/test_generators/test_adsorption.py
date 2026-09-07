from pymatgen.core import Lattice, Molecule, Structure


def _slab():
    return Structure(Lattice.from_parameters(4, 4, 12, 90, 90, 90), ["Cu", "Cu", "Cu", "Cu"], [[0, 0, .2], [.5, 0, .2], [0, .5, .2], [.5, .5, .2]])


def test_adsorption_generator_algorithm_only_is_deterministic_and_records_evidence():
    from llm_matgen.generators.adsorption import AdsorptionGenerator, AdsorptionInput, AdsorptionParams

    inputs = AdsorptionInput(slab=_slab(), molecule=Molecule(["H"], [[0, 0, 0]]), anchor_index=1)
    params = AdsorptionParams(max_structures=2, fixed_bottom_layers=1)
    first = AdsorptionGenerator().generate(inputs, params)
    second = AdsorptionGenerator().generate(inputs, params)
    assert first.generated_count == 2
    assert [item.record.structure_id for item in first.generated] == [item.record.structure_id for item in second.generated]
    assert "proposal" in first.generated[0].record.actual_parameters


def test_adsorption_generator_require_history_fails_without_history():
    import pytest
    from llm_matgen.generators.adsorption import AdsorptionGenerator, AdsorptionInput, AdsorptionParams

    inputs = AdsorptionInput(slab=_slab(), molecule=Molecule(["H"], [[0, 0, 0]]), anchor_index=1)
    with pytest.raises(ValueError, match="history"):
        AdsorptionGenerator().generate(inputs, AdsorptionParams(history_mode="require"))


def test_adsorption_generator_enforces_atom_limit():
    import pytest
    from llm_matgen.generators.adsorption import AdsorptionGenerator, AdsorptionInput, AdsorptionParams

    inputs = AdsorptionInput(slab=_slab(), molecule=Molecule(["H"], [[0, 0, 0]]), anchor_index=1)
    with pytest.raises(ValueError, match="max_atoms_per_structure"):
        AdsorptionGenerator().generate(inputs, AdsorptionParams(max_atoms_per_structure=4))


def test_prefer_history_falls_back_to_algorithmic_when_history_candidate_is_invalid():
    from llm_matgen.generators.adsorption import AdsorptionGenerator, AdsorptionInput, AdsorptionParams

    inputs = AdsorptionInput(slab=_slab(), molecule=Molecule(["H"], [[0, 0, 0]]), anchor_index=1)
    history = ({
        "revision_id": "invalid-contact",
        "fractional_site": (0.0, 0.0, 0.2),
        "side": "top",
        "local_adsorbate_coordinates": ((0.0, 0.0, 0.0),),
        "local_delta": (0.0, 0.0, -2.0),
    },)
    result = AdsorptionGenerator(history=history).generate(inputs, AdsorptionParams(history_mode="prefer", max_structures=1))
    assert result.generated[0].record.actual_parameters["proposal"]["source"] == "algorithmic"
