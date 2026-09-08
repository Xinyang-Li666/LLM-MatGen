from pathlib import Path
import json

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
        ".llm-matgen/",
        "revisions/",
        ".sqs-deps/",
    } <= entries


def test_env_example_contains_only_a_placeholder_mp_key() -> None:
    assignments = [
        line.strip()
        for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert assignments == ["MP_API_KEY=your-mp-api-key"]


def test_mit_license_is_present_and_declared():
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "MIT License" in license_text
    assert 'license = { text = "MIT" }' in pyproject


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


def test_scanner_detects_json_escaped_absolute_paths() -> None:
    escaped_path = "D:" + "\\\\科研\\\\LLM-MatGen\\\\tests\\\\nl-tests\\\\state.json"
    findings = scan_text(Path("state.json"), json.dumps({"path": escaped_path}))

    assert {finding.rule for finding in findings} == {"personal-absolute-path"}


def test_scanner_detects_ssh_wrappers_without_echoing_commands() -> None:
    findings = scan_text(
        Path("wrapper.ps1"),
        "ProxyCommand powershell -File C:\\Users\\alice\\ssh-wrapper.ps1\n",
    )
    assert {finding.rule for finding in findings} == {"personal-absolute-path", "ssh-wrapper"}


def test_public_docs_cover_viewer_cases_and_generation_boundary() -> None:
    texts = [
        (ROOT / "README.md").read_text(encoding="utf-8"),
        (ROOT / "docs/user-guide.zh-CN.md").read_text(encoding="utf-8"),
        (ROOT / "docs/api.md").read_text(encoding="utf-8"),
        (ROOT / "docs/mcp.md").read_text(encoding="utf-8"),
    ]
    for text in texts:
        assert "viewer" in text.lower()
        assert "adsorption" in text.lower()
        assert "结构生成" in text or "structure generation" in text.lower()


def test_tracked_repository_text_is_release_safe() -> None:
    assert scan_repository(ROOT) == []
