import numpy as np
import pytest
from pymatgen.core import Lattice, Molecule, Structure


def _slab():
    return Structure(Lattice.cubic(5), ["Cu"], [[0, 0, 0]])


def test_history_pose_maps_fractional_site_to_new_slab_without_copying_old_cartesian():
    from llm_matgen.adsorption.proposals import RetrievedProposalSource

    source = RetrievedProposalSource(
        _slab(), Molecule(["H"], [[0, 0, 0]]),
        history=({"revision_id": "r1", "site_kind": "ontop", "fractional_site": (0.5, 0.5, 0.0), "side": "top"},),
        height=2.0,
    )
    proposal = next(source.iter_proposals())
    assert proposal.source == "history"
    assert proposal.site_id == "history:r1"
    assert np.allclose(proposal.cartesian_site, [2.5, 2.5, 2.0])


def test_resolve_history_modes_are_explicit_and_prefer_falls_back():
    from llm_matgen.adsorption.proposals import resolve_history

    fallback = object()
    assert resolve_history("off", None, fallback) == (fallback, None)
    assert resolve_history("prefer", None, fallback)[0] is fallback
    assert "fallback" in resolve_history("prefer", None, fallback)[1]
    with pytest.raises(ValueError):
        resolve_history("require", None, fallback)

