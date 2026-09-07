from pymatgen.core import Lattice, Molecule, Structure


def _slab():
    return Structure(Lattice.from_parameters(4, 4, 12, 90, 90, 90), ["Cu"], [[0, 0, 0.2]])


def _candidate(z=5.0):
    slab = _slab()
    return Structure(slab.lattice, ["Cu", "H"], [[0, 0, 0.2], [0.5, 0.5, z]], coords_are_cartesian=True)


def test_validator_accepts_reasonable_candidate_and_reports_stable_measurements():
    from llm_matgen.adsorption.validation import AdsorptionCandidateValidator

    report = AdsorptionCandidateValidator(_slab(), Molecule(["H"], [[0, 0, 0]])).validate(_candidate())
    assert report.valid
    assert report.issues == ()
    assert "vacuum" in report.measurements


def test_validator_rejects_collision_and_fixed_flag_mismatch_with_codes():
    from llm_matgen.adsorption.validation import AdsorptionCandidateValidator

    report = AdsorptionCandidateValidator(_slab(), Molecule(["H"], [[0, 0, 0]]), min_distance=1.0).validate(_candidate(z=0.2), expected_flags=((False, False, False), (True, True, True)))
    assert not report.valid
    assert {issue.code for issue in report.issues} >= {"slab_collision", "fixed_flags_mismatch"}


def test_validator_checks_anchor_window_and_periodic_adsorbate_images():
    from llm_matgen.adsorption.validation import AdsorptionCandidateValidator

    slab = Structure(Lattice.from_parameters(3, 3, 14, 90, 90, 90), ["Cu"], [[0, 0, 0.2]])
    molecule = Molecule(["C", "H"], [[0, 0, 0], [1.1, 0, 0]])
    candidate = Structure(slab.lattice, ["Cu", "C", "H"], [[0, 0, 2.8], [0.1, 0.1, 5.0], [1.2, 0.1, 5.0]], coords_are_cartesian=True)
    report = AdsorptionCandidateValidator(
        slab, molecule, anchor_index=0, anchor_contact_window=(0.5, 1.0), min_vacuum=0.0
    ).validate(candidate)
    assert not report.valid
    assert "anchor_contact_out_of_window" in {issue.code for issue in report.issues}


def test_validator_reports_element_radius_overlap_and_side_vacuum():
    from llm_matgen.adsorption.validation import AdsorptionCandidateValidator

    slab = Structure(Lattice.from_parameters(4, 4, 8, 90, 90, 90), ["Cu"], [[0, 0, 0.5]])
    molecule = Molecule(["O", "O"], [[0, 0, 0], [0.7, 0, 0]])
    candidate = Structure(slab.lattice, ["Cu", "O", "O"], [[0, 0, 4], [1, 1, 5], [1.7, 1, 5]], coords_are_cartesian=True)
    report = AdsorptionCandidateValidator(slab, molecule, min_vacuum=0.0, min_vacuum_each_side=2.0).validate(candidate)
    codes = {issue.code for issue in report.issues}
    assert "covalent_overlap" in codes or "adsorbate_internal_collision" in codes
    assert "vacuum_side_too_small" in codes
