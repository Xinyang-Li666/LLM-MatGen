import numpy as np
import pytest
from pymatgen.core import Lattice, Molecule, Structure


def _slab():
    return Structure(Lattice.cubic(4), ["Cu"], [[0, 0, 0]])


def _molecule():
    return Molecule(["H"], [[0, 0, 0]])


def test_adsorption_input_uses_one_based_cli_anchor_and_zero_based_derived_value():
    from llm_matgen.generators.adsorption import AdsorptionInput

    value = AdsorptionInput(slab=_slab(), molecule=_molecule(), anchor_index=1)
    assert value.anchor_index == 1
    assert value.anchor_index_zero_based == 0


@pytest.mark.parametrize("anchor", [0, 2, -1])
def test_adsorption_input_rejects_invalid_anchor(anchor):
    from llm_matgen.generators.adsorption import AdsorptionInput
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AdsorptionInput(slab=_slab(), molecule=_molecule(), anchor_index=anchor)


def test_adsorption_params_reject_nonfinite_pose_and_unbounded_limits():
    from llm_matgen.generators.adsorption import AdsorptionParams
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AdsorptionParams(site_height=float("nan"))
    with pytest.raises(ValidationError):
        AdsorptionParams(max_structures=0)


def test_dft_handoff_matrix_is_explicit_and_serializable():
    from llm_matgen.generators.adsorption import DFTHandoffMatrix

    handoff = DFTHandoffMatrix(
        matrix=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        vacuum_axis=2,
        notes=("vacuum and spin require user verification",),
    )
    assert np.linalg.det(np.array(handoff.matrix)) == pytest.approx(1.0)
    assert handoff.model_dump(mode="json")["vacuum_axis"] == 2


def test_multi_atom_adsorbate_requires_reference_axis_and_matching_charge_spin():
    from llm_matgen.generators.adsorption import AdsorptionInput
    from pydantic import ValidationError

    molecule = Molecule(["O", "H"], [[0, 0, 0], [0, 0, 1]])
    with pytest.raises(ValidationError, match="reference axis"):
        AdsorptionInput(slab=_slab(), molecule=molecule, anchor_index=1)
    with pytest.raises(ValidationError, match="charge"):
        AdsorptionInput(slab=_slab(), molecule=molecule, anchor_index=1, reference_axis=(0, 0, 1), charge=1)
    with pytest.raises(ValidationError, match="finite"):
        AdsorptionInput(slab=_slab(), molecule=molecule, anchor_index=1, reference_axis=(0, 0, float("nan")))


def test_adsorption_params_bound_pose_sets_and_aliases():
    from llm_matgen.generators.adsorption import AdsorptionParams
    from pydantic import ValidationError

    params = AdsorptionParams(history_policy="prefer", site_types=("hollow4",), azimuths=(0, 90), max_structures=2, max_proposal_attempts=20)
    assert params.history_mode == "prefer"
    assert params.site_kinds == ("hollow4",)
    assert params.max_attempts == 20
    with pytest.raises(ValidationError):
        AdsorptionParams(azimuths=(float("inf"),))
    with pytest.raises(ValidationError):
        AdsorptionParams(site_types=("unknown",))


def test_typed_adsorption_result_retains_roles_and_handoff_contract():
    from llm_matgen.generators.adsorption import AdsorptionGenerationResult, DFTHandoffMatrix

    slab = _slab()
    molecule = _molecule()
    handoff = DFTHandoffMatrix(matrix=tuple(tuple(float(x) for x in row) for row in slab.lattice.matrix))
    left = AdsorptionGenerationResult(clean_slab=slab, adsorbate=molecule, dft_handoff=handoff)
    right = AdsorptionGenerationResult(clean_slab=slab.copy(), adsorbate=molecule.copy(), dft_handoff=handoff)
    assert left.combine(right).clean_slab is not None
