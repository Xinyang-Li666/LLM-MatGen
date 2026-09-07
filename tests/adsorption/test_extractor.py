from pathlib import Path


def _snapshot(tmp_path: Path, **metadata):
    from llm_matgen.adsorption.sources.base import JobSnapshot, RemoteFileSnapshot

    files = tuple(
        RemoteFileSnapshot(name, len(name), 1, name.ljust(64, "0"))
        for name in ("POSCAR", "CONTCAR", "INCAR", "OUTCAR", "clean_slab/POSCAR")
    )
    return JobSnapshot("case", "local", files, metadata)


def test_normal_case_is_eligible_and_outcar_is_not_an_artifact(tmp_path: Path):
    from llm_matgen.adsorption.extractor import CaseExtractor, CaseStatus

    result = CaseExtractor().extract(_snapshot(tmp_path))

    assert result.status is CaseStatus.ELIGIBLE
    assert result.audit.rejection_reasons == ()
    assert "OUTCAR" not in result.artifacts
    assert result.features is not None


def test_quality_gates_have_deterministic_rejections(tmp_path: Path):
    from llm_matgen.adsorption.extractor import CaseExtractor

    cases = [
        ({"ionic_converged": False}, "rejected_ionic_unconverged", "ionic_not_converged"),
        ({"electronic_converged": False}, "rejected_electronic_unconverged", "electronic_not_converged"),
        ({"fatal_warning": True}, "rejected_fatal_warning", "fatal_marker"),
        ({"run_type": "neb"}, "rejected_incomplete", "neb_run"),
        ({"run_type": "static"}, "rejected_incomplete", "static_run"),
        ({"stable": False}, "rejected_incomplete", "unstable_files"),
    ]
    for metadata, status, reason in cases:
        result = CaseExtractor().extract(_snapshot(tmp_path, **metadata))
        assert result.status.value == status
        assert reason in result.audit.rejection_reasons


def test_missing_clean_slab_is_rejected_and_audited(tmp_path: Path):
    from llm_matgen.adsorption.extractor import CaseExtractor
    from llm_matgen.adsorption.sources.base import JobSnapshot, RemoteFileSnapshot

    files = tuple(RemoteFileSnapshot(name, len(name), 1, name.ljust(64, "0")) for name in ("POSCAR", "CONTCAR", "INCAR", "OUTCAR"))
    result = CaseExtractor().extract(JobSnapshot("case", "local", files, {}))

    assert result.status.value == "rejected_incomplete"
    assert "clean_parent_missing" in result.audit.rejection_reasons


def test_revision_identity_is_stable_for_same_snapshot(tmp_path: Path):
    from llm_matgen.adsorption.extractor import CaseExtractor

    first = CaseExtractor().extract(_snapshot(tmp_path))
    second = CaseExtractor().extract(_snapshot(tmp_path))

    assert first.exact_hash == second.exact_hash
    assert first.revision_id == second.revision_id
