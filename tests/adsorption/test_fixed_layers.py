import numpy as np
from pymatgen.core import Lattice, Structure


def _slab():
    return Structure(
        Lattice.from_parameters(4, 4, 10, 80, 90, 90),
        ["Cu", "Cu", "Cu", "H"],
        [[0, 0, 0.10], [0.5, 0, 0.10], [0, 0.5, 0.30], [0.5, 0.5, 0.70]],
        site_properties={"selective_dynamics": [(False, False, False), (True, True, True), (True, True, True), (True, True, True)]},
    )


def test_layer_ids_use_true_surface_normal_and_slab_atom_count():
    from llm_matgen.adsorption.validation import _layer_ids

    layers, projections = _layer_ids(_slab(), slab_atom_count=3, tolerance=0.2)
    assert len(layers) == 2
    assert set(layers[0]) == {0, 1}
    assert len(projections) == 3


def test_apply_fixed_bottom_layers_unions_existing_flags_and_reports_warning():
    from llm_matgen.adsorption.validation import apply_fixed_bottom_layers

    result = apply_fixed_bottom_layers(_slab(), slab_atom_count=3, n_layers=1, tolerance=0.2, side="both")
    assert result.flags[0] == (False, False, False)
    assert result.flags[1] == (False, False, False)
    assert result.flags[2] == (True, True, True)
    assert result.flags[3] == (True, True, True)
    assert any("both" in warning for warning in result.warnings)


def test_apply_fixed_layers_uses_top_surface_and_keeps_adsorbate_movable():
    from llm_matgen.adsorption.validation import apply_fixed_bottom_layers

    result = apply_fixed_bottom_layers(_slab(), slab_atom_count=3, n_layers=1, tolerance=0.2, side="top")
    assert result.flags[2] == (False, False, False)
    assert result.flags[3] == (True, True, True)
