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
