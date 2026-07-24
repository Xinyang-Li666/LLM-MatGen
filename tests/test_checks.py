from llm_matgen.generators.models import CheckLevel
from pymatgen.core import Lattice, Structure


def make_fixture() -> Structure:
    return Structure(
        Lattice.cubic(4.2),
        ["Li", "Co", "O", "O"],
        [[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0.5, 0], [0.5, 0, 0.5]],
    )


def test_check_report_serializes_issues_and_computes_exportability():
    from llm_matgen.checks.models import CheckIssue, CheckReport

    warning = CheckIssue(
        code="close-contact",
        level=CheckLevel.WARNING,
        message="two sites are close",
        site_ids=["site-a", "site-b"],
        details={"distance": 0.7},
    )
    report = CheckReport(
        n_atoms=2,
        formula="LiO",
        issues=[warning],
        metrics={"min_distance": 0.7},
    )

    assert report.can_export is True
    restored = CheckReport.model_validate_json(report.model_dump_json())
    assert restored == report


def test_check_report_with_error_cannot_export():
    from llm_matgen.checks.models import CheckIssue, CheckReport

    report = CheckReport(
        n_atoms=0,
        formula="",
        issues=[
            CheckIssue(
                code="empty-structure",
                level=CheckLevel.ERROR,
                message="structure has no sites",
            )
        ],
    )

    assert report.can_export is False


def test_light_checker_reports_hard_errors_and_non_blocking_close_contacts():
    from llm_matgen.checks.checker import LightStructureChecker

    checker = LightStructureChecker()
    normal = checker.check(make_fixture())
    assert normal.can_export is True
    assert not any(issue.level is CheckLevel.ERROR for issue in normal.issues)

    empty = checker.check(Structure(Lattice.cubic(4), [], []))
    assert any(issue.code == "empty-structure" for issue in empty.issues)

    singular = Structure(Lattice([[1, 0, 0], [0, 1, 0], [0, 0, 0]]), ["Li"], [[0, 0, 0]])
    singular_report = checker.check(singular)
    assert any(issue.code == "singular-lattice" for issue in singular_report.issues)

    too_close = Structure(
        Lattice.cubic(4),
        ["Li", "O"],
        [[0, 0, 0], [0.01, 0, 0]],
    )
    close_report = checker.check(too_close, min_distance=0.8)
    assert close_report.can_export is True
    assert any(issue.code == "close-contact" for issue in close_report.issues)


def test_light_checker_records_reference_composition_metrics():
    from llm_matgen.checks.checker import LightStructureChecker

    original = make_fixture()
    changed = original.copy()
    changed.replace(0, "Na")
    report = LightStructureChecker().check(changed, reference=original)

    assert report.metrics["reference_n_atoms"] == len(original)
    assert report.metrics["composition_changed"] is True
