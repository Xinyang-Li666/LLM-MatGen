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


def test_history_final_local_pose_and_delta_are_mapped_in_current_frame():
    from llm_matgen.adsorption.proposals import RetrievedProposalSource

    source = RetrievedProposalSource(
        _slab(), Molecule(["O", "H"], [[0, 0, 0], [0, 0, 1]]),
        history=({
            "revision_id": "r2", "site_kind": "bridge", "fractional_site": (0.5, 0.5, 0.0), "side": "top",
            "local_adsorbate_coordinates": ((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
            "local_delta": (0.1, -0.2, 0.0),
        },), height=2.0,
    )
    proposal = next(source.iter_proposals())
    assert proposal.adsorbate_coords.shape == (2, 3)
    assert np.linalg.norm(proposal.adsorbate_coords[1] - proposal.adsorbate_coords[0]) == pytest.approx(1.0)


def test_history_malformed_pose_is_rejected_instead_of_silently_falling_back():
    from llm_matgen.adsorption.proposals import RetrievedProposalSource

    source = RetrievedProposalSource(_slab(), Molecule(["H"], [[0, 0, 0]]), history=({
        "revision_id": "bad", "fractional_site": (0.5, 0.5, 0.0), "side": "top",
        "local_adsorbate_coordinates": ((0.0, 0.0),),
    },))
    with pytest.raises(ValueError, match="local"):
        next(source.iter_proposals())


def test_history_factory_errors_fall_back_only_in_prefer_mode():
    from llm_matgen.adsorption.proposals import resolve_history

    def broken():
        raise OSError("store unavailable")

    fallback = object()
    selected, reason = resolve_history("prefer", broken, fallback)
    assert selected is fallback and "store" in reason
    with pytest.raises(ValueError, match="required"):
        resolve_history("require", broken, fallback)
