import numpy as np
from pymatgen.core import Lattice, Molecule, Structure


def _slab():
    return Structure(
        Lattice.from_parameters(4, 4, 12, 90, 90, 90),
        ["Cu", "Cu", "Cu", "Cu"],
        [[0, 0, 0.20], [0.5, 0, 0.20], [0, 0.5, 0.20], [0.5, 0.5, 0.20]],
    )


def test_surface_frame_has_true_top_and_bottom_normals():
    from llm_matgen.adsorption.proposals import SurfaceFrame

    top = SurfaceFrame.from_slab(_slab(), side="top")
    bottom = SurfaceFrame.from_slab(_slab(), side="bottom")
    assert np.dot(top.normal, bottom.normal) == -1.0
    assert abs(np.linalg.norm(top.normal) - 1) < 1e-12


def test_algorithmic_source_generates_stable_site_ids_and_requested_sides():
    from llm_matgen.adsorption.proposals import AlgorithmicProposalSource

    source = AlgorithmicProposalSource(_slab(), Molecule(["H"], [[0, 0, 0]]), height=2.0)
    top = list(source.iter_proposals(site_kinds=("ontop",), side="top"))
    bottom = list(source.iter_proposals(site_kinds=("ontop",), side="bottom"))
    assert top and bottom
    assert [item.site_id for item in top] == sorted(item.site_id for item in top)
    assert np.dot(top[0].frame.normal, bottom[0].frame.normal) < 0
    assert top[0].adsorbate_coords.shape == (1, 3)


def test_explicit_cartesian_site_is_supported_and_sorted():
    from llm_matgen.adsorption.proposals import AlgorithmicProposalSource

    source = AlgorithmicProposalSource(_slab(), Molecule(["H"], [[0, 0, 0]]), height=1.5)
    proposals = list(source.iter_proposals(explicit_sites=(("custom", (1, 2, 3)),)))
    assert len(proposals) == 1
    assert proposals[0].site_id == "custom"
    assert np.allclose(proposals[0].cartesian_site, [1, 2, 3])

