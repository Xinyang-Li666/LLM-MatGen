from __future__ import annotations

from pathlib import Path

import numpy as np

from llm_matgen.trajectories.filtering.models import FilterFrame
from llm_matgen.trajectories.representative.engine import RepresentativeSamplingEngine
from llm_matgen.trajectories.representative.models import RepresentativeSamplingRequest, SourceSpec


class SpySOAPBackend:
    def describe(self, frame):
        return np.array([float(frame.source_index), float(frame.source_index % 2)])


def test_soap_backend_uses_common_engine_and_proportional_quota(tmp_path: Path):
    specs = (SourceSpec("one", Path("one.extxyz"), "extxyz"), SourceSpec("two", Path("two.extxyz"), "extxyz"))
    frames = lambda n: [FilterFrame(np.array([5]), np.array([[i, 0, 0.]]), np.diag([8., 8., 8.]), np.array([True] * 3), source_index=i) for i in range(n)]
    request = RepresentativeSamplingRequest(specs, "soap-fps", 3, output_root=tmp_path)
    result = RepresentativeSamplingEngine(request, SpySOAPBackend()).run({"one": frames(2), "two": frames(4)})
    assert result.selected_count == 3
    assert result.selected_path.exists()


def test_soap_warm_start_prefers_candidate_far_from_existing(tmp_path: Path):
    specs = (SourceSpec("one", Path("one.extxyz"), "extxyz"),)
    frames = [FilterFrame(np.array([5]), np.array([[i, 0, 0.]]), np.diag([8., 8., 8.]), np.array([True] * 3), source_index=i) for i in range(3)]
    request = RepresentativeSamplingRequest(specs, "soap-fps", 1, output_root=tmp_path)
    result = RepresentativeSamplingEngine(request, SpySOAPBackend()).run({"one": frames}, warm_start={"one": np.array([[0., 0.]])})
    assert '"source_index": 2' in result.selection_path.read_text(encoding="utf-8")
