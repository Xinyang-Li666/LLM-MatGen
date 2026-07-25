from pathlib import Path


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
