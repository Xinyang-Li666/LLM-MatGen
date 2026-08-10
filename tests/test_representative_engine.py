from __future__ import annotations

from pathlib import Path

import numpy as np
from ase.io import read

from llm_matgen.trajectories.filtering.models import FilterFrame
from llm_matgen.trajectories.representative.engine import RepresentativeSamplingEngine
from llm_matgen.trajectories.representative.models import RepresentativeSamplingRequest, SourceSpec


class FakeDescriptor:
    def describe(self, frame):
        return np.array([float(frame.source_index), float(frame.natoms)])


def source_frames(name: str, count: int):
    return [FilterFrame(np.array([5]), np.array([[float(i), 0, 0]]), np.diag([10., 10., 10.]), np.array([True] * 3), source_index=i) for i in range(count)]


def test_engine_allocates_sources_and_exports(tmp_path: Path):
    specs = tuple(SourceSpec(n, Path(f"{n}.extxyz"), "extxyz") for n in ("a", "b", "c"))
    request = RepresentativeSamplingRequest(specs, "rdf-fps", 5, output_root=tmp_path)
    result = RepresentativeSamplingEngine(request, FakeDescriptor()).run({"a": source_frames("a", 2), "b": source_frames("b", 5), "c": source_frames("c", 10)})
    assert result.selected_count == 5
    assert Path(result.selected_path).exists()
    assert len(read(result.selected_path, index=":")) == 5


def test_global_mode_and_min_distance_stop(tmp_path: Path):
    specs = (SourceSpec("a", Path("a.extxyz"), "extxyz"), SourceSpec("b", Path("b.extxyz"), "extxyz"))
    request = RepresentativeSamplingRequest(specs, "rdf-fps", 4, allocation="global", min_distance=10.0, output_root=tmp_path)
    result = RepresentativeSamplingEngine(request, FakeDescriptor()).run({"a": source_frames("a", 2), "b": source_frames("b", 2)})
    assert result.selected_count == 1


def test_streaming_engine_uses_factories_and_memmap_workspace(tmp_path: Path):
    specs = (SourceSpec("a", Path("a.extxyz"), "extxyz"), SourceSpec("b", Path("b.extxyz"), "extxyz"))
    request = RepresentativeSamplingRequest(specs, "rdf-fps", 3, output_root=tmp_path)
    factories = {"a": lambda: iter(source_frames("a", 2)), "b": lambda: iter(source_frames("b", 4))}
    result = RepresentativeSamplingEngine(request, FakeDescriptor()).run_streaming(factories, {"a": 2, "b": 4})
    assert result.selected_count == 3
    assert not (tmp_path / ".descriptor-work").exists()
