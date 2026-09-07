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
