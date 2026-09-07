from pathlib import Path

import pytest


def _write_job(root: Path, name: str, outcar: str = "OUTCAR\n") -> Path:
    job = root / name
    job.mkdir(parents=True, exist_ok=True)
    (job / "POSCAR").write_text("POSCAR\n", encoding="utf-8")
    (job / "OUTCAR").write_text(outcar, encoding="utf-8")
    return job


def test_discover_is_stably_sorted_and_includes_root_job(tmp_path: Path):
    from llm_matgen.adsorption.sources.local import LocalDirectoryCaseSource

    (tmp_path / "POSCAR").write_text("root\n", encoding="utf-8")
    _write_job(tmp_path, "zeta")
    _write_job(tmp_path, "alpha")
    source = LocalDirectoryCaseSource(tmp_path)

    jobs = source.discover()

    assert [job.job_id for job in jobs] == [".", "alpha", "zeta"]
    assert all(job.source == "local" for job in jobs)


def test_snapshot_contains_stable_relative_paths_size_mtime_and_hash(tmp_path: Path):
    from llm_matgen.adsorption.sources.local import LocalDirectoryCaseSource

    job = _write_job(tmp_path, "case")
    snapshot = LocalDirectoryCaseSource(tmp_path).snapshot("case")
    outcar = next(item for item in snapshot.files if item.relative_path == "OUTCAR")

    assert outcar.size == (job / "OUTCAR").stat().st_size
    assert len(outcar.sha256) == 64
    assert outcar.relative_path == "OUTCAR"
    assert [item.relative_path for item in snapshot.files] == ["OUTCAR", "POSCAR"]


@pytest.mark.parametrize("value", ["../case", "a/../../case", str(Path.cwd().anchor) + "case", "bad\x00path"])
def test_snapshot_rejects_path_escape_and_nul(tmp_path: Path, value: str):
    from llm_matgen.adsorption.sources.local import CaseSourceError, LocalDirectoryCaseSource

    with pytest.raises(CaseSourceError):
        LocalDirectoryCaseSource(tmp_path).snapshot(value)


def test_discover_does_not_follow_symlink_outside_root(tmp_path: Path):
    from llm_matgen.adsorption.sources.local import LocalDirectoryCaseSource

    outside = tmp_path.parent / "outside-case"
    _write_job(tmp_path, "inside")
    _write_job(tmp_path, "outside-temp")
    outside.mkdir(exist_ok=True)
    (outside / "POSCAR").write_text("outside\n", encoding="utf-8")
    link = tmp_path / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links are unavailable")

    jobs = LocalDirectoryCaseSource(tmp_path).discover()

    assert all(job.job_id != "linked" for job in jobs)


def test_large_outcar_is_streamed_without_reading_entire_file(tmp_path: Path, monkeypatch):
    from llm_matgen.adsorption.sources.local import LocalDirectoryCaseSource

    job = _write_job(tmp_path, "case", outcar="x" * 100_000)
    original_read_text = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("whole file read")))

    snapshot = LocalDirectoryCaseSource(tmp_path).snapshot(job.name)

    assert next(item for item in snapshot.files if item.relative_path == "OUTCAR").size == 100_000
    monkeypatch.setattr(Path, "read_text", original_read_text)


def test_snapshot_detects_file_changed_during_hash(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace

    from llm_matgen.adsorption.sources.local import CaseSourceError, LocalDirectoryCaseSource

    _write_job(tmp_path, "case")
    source = LocalDirectoryCaseSource(tmp_path)
    original = source._file_stat
    calls = {"count": 0}

    def changing_stat(path: Path):
        value = original(path)
        calls["count"] += 1
        if calls["count"] == 2 and path.name == "OUTCAR":
            return SimpleNamespace(st_size=value.st_size + 1, st_mtime_ns=value.st_mtime_ns)
        return value

    monkeypatch.setattr(source, "_file_stat", changing_stat)
    with pytest.raises(CaseSourceError, match="changed during snapshot"):
        source.snapshot("case")
