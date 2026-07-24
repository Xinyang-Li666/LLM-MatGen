from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure

from llm_matgen.generators.models import OutputFormat
from llm_matgen.io.exporters import ExportOptions, StructureExporter


def fixture_structure() -> Structure:
    return Structure(Lattice.cubic(4.2), ["Co", "O"], [[0, 0, 0], [0.5, 0.5, 0.5]])


@pytest.mark.parametrize("fmt", list(OutputFormat))
def test_local_source_reads_all_supported_formats(tmp_path: Path, fmt):
    from llm_matgen.sources.local import LocalStructureSource

    artifact = StructureExporter().export_structure(
        fixture_structure(),
        "fixture",
        ExportOptions(formats=[fmt], output_dir=tmp_path),
    ).artifacts[0]
    source = LocalStructureSource(
        allowed_roots=[tmp_path],
        lammps_element_map={1: "Co", 2: "O"},
    ).get(str(artifact.path))
    assert source.source_kind == "local"
    assert source.structure.composition == fixture_structure().composition
    assert source.local_path == artifact.path.resolve()
    assert source.structure_hash == source.artifact_id


def test_local_source_rejects_missing_directory_corruption_and_root_escape(tmp_path: Path):
    from llm_matgen.sources.local import LocalSourceError, LocalStructureSource

    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    corrupt = allowed / "bad.cif"
    corrupt.write_text("not a cif", encoding="utf-8")
    source = LocalStructureSource(allowed_roots=[allowed])
    with pytest.raises(LocalSourceError, match="does not exist"):
        source.get(str(allowed / "missing.cif"))
    with pytest.raises(LocalSourceError, match="regular file"):
        source.get(str(allowed))
    with pytest.raises(LocalSourceError, match="parse"):
        source.get(str(corrupt))
    outside_file = outside / "escaped.cif"
    outside_file.write_text("data_test", encoding="utf-8")
    with pytest.raises(LocalSourceError, match="allowed roots"):
        source.get(str(outside_file))


def test_local_source_resolves_symlink_before_root_check(tmp_path: Path):
    from llm_matgen.sources.local import LocalSourceError, LocalStructureSource

    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    target = outside / "target.cif"
    target.write_text("data_test", encoding="utf-8")
    link = allowed / "link.cif"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(LocalSourceError, match="allowed roots"):
        LocalStructureSource(allowed_roots=[allowed]).get(str(link))
