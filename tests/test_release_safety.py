from pathlib import Path

from llm_matgen.release_safety import format_findings, scan_repository, scan_text


ROOT = Path(__file__).resolve().parents[1]


def test_gitignore_covers_local_secrets_and_generated_artifacts() -> None:
    entries = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    assert {
        ".env",
        ".env.*",
        "!.env.example",
        "*.db",
        "*.sqlite",
        "*.sqlite3",
        "output/",
        "downloads/",
        "test-results/",
        "tests/nl-tests/mp-downloads/",
        "tests/nl-tests/output/",
        "tests/nl-tests/*-result.json",
    } <= entries


def test_env_example_contains_only_a_placeholder_mp_key() -> None:
    assignments = [
        line.strip()
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert assignments == ["MP_API_KEY=your-mp-api-key"]


def test_scanner_detects_secrets_and_personal_absolute_paths() -> None:
    secret = "live-" + "A" * 32
    personal_path = "C:" + "\\Users\\alice\\project\\config.json"
    findings = scan_text(
        Path("config.txt"),
        f"MP_API_KEY={secret}\ncache={personal_path}\n",
    )

    assert {finding.rule for finding in findings} == {
        "non-placeholder-secret",
        "personal-absolute-path",
    }


def test_scanner_allows_documented_placeholders() -> None:
    findings = scan_text(
        Path(".env.example"),
        "MP_API_KEY=your-mp-api-key\npath=C:\\Users\\<username>\\project\n",
    )

    assert findings == []


def test_scanner_report_never_echoes_matching_content() -> None:
    secret = "live-" + "B" * 32
    findings = scan_text(Path("local.env"), f"MP_API_KEY={secret}\n")

    report = format_findings(findings)

    assert secret not in report
    assert report == "local.env: non-placeholder-secret"


def test_tracked_repository_text_is_release_safe() -> None:
    assert scan_repository(ROOT) == []
