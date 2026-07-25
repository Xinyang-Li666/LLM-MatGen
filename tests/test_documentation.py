from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_COMMANDS = (
    "search",
    "download",
    "properties",
    "substrates",
    "generate",
    "check",
    "export",
    "db",
    "mcp",
    "config",
)


def test_user_guide_documents_lammps_fallback_and_mp_properties():
    guide = (ROOT / "docs" / "user-guide.zh-CN.md").read_text(encoding="utf-8")
    for term in ("原子序数", "显式映射优先", "TYPE=ELEMENT"):
        assert term in guide
    for field in (
        "energy_above_hull",
        "band_gap",
        "is_magnetic",
        "epsilon_static",
        "phonon_dos",
        "shear_modulus",
    ):
        assert field in guide
    for field in ("available", "endpoint", "method", "error"):
        assert f"`{field}`" in guide


def test_user_guide_documents_structure_based_substrate_search():
    guide = (ROOT / "docs" / "user-guide.zh-CN.md").read_text(encoding="utf-8")
    for field in ("film_id", "sub_id", "sub_form", "film_orient", "orient", "area", "energy"):
        assert f"`{field}`" in guide
    assert "MP material ID" in guide
    assert "本地 CIF/POSCAR" in guide


def test_public_docs_do_not_bind_to_specific_model_vendor():
    for relative in ("README.md", "docs/user-guide.zh-CN.md"):
        text = (ROOT / relative).read_text(encoding="utf-8").lower()
        assert "openai" not in text
        assert "anthropic" not in text
        assert "all-llm" not in text


def test_readme_and_user_guide_cover_every_public_cli_command():
    for relative in ("README.md", "docs/user-guide.zh-CN.md"):
        text = (ROOT / relative).read_text(encoding="utf-8")
        for command in PUBLIC_COMMANDS:
            assert f"llm-matgen {command}" in text, f"{relative} misses {command}"


def test_public_markdown_relative_links_exist():
    import re

    sources = [ROOT / "README.md", *(ROOT / "docs").rglob("*.md")]
    for source in sources:
        text = source.read_text(encoding="utf-8")
        for target in re.findall(r"(?<!!)\[[^]]*]\(([^)]+)\)", text):
            path_text = target.split("#", 1)[0]
            if not path_text or "://" in path_text or path_text.startswith("mailto:"):
                continue
            assert (source.parent / path_text).exists(), f"{source}: missing {target}"


def test_user_guide_documents_output_root_workspace_boundary():
    guide = (ROOT / "docs/user-guide.zh-CN.md").read_text(encoding="utf-8")
    assert "`--output-root` 必须位于当前工作目录内部" in guide
