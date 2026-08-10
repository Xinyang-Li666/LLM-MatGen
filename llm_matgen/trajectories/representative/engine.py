"""In-memory orchestration for representative FPS sampling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from llm_matgen.trajectories.filtering.models import FilterFrame
from .fps import centered_fps
from .models import RepresentativeSamplingRequest, RepresentativeSamplingResult, SelectionRecord
from .quotas import allocate_proportional_quotas
from .writers import write_outputs


class RepresentativeSamplingEngine:
    def __init__(self, request: RepresentativeSamplingRequest, descriptor):
        if request.method not in {"rdf-fps", "soap-fps"}:
            raise ValueError(f"unsupported sampling method: {request.method}")
        self.request = request
        self.descriptor = descriptor

    def run(self, frames_by_source: Mapping[str, Sequence[FilterFrame]]) -> RepresentativeSamplingResult:
        ordered = [(spec.name, list(frames_by_source.get(spec.name, ()))) for spec in self.request.sources]
        counts = {name: len(frames) for name, frames in ordered}
        total = sum(counts.values())
        if total == 0:
            raise ValueError("no candidate frames were provided")
        budget = min(self.request.count, total)
        quotas = allocate_proportional_quotas(counts, budget) if self.request.allocation == "proportional" else {name: 0 for name in counts}
        selected_pairs: list[tuple[FilterFrame, SelectionRecord]] = []
        if self.request.allocation == "global":
            all_frames = [(name, frame) for name, frames in ordered for frame in frames]
            matrix = self._describe([frame for _, frame in all_frames])
            result = centered_fps(matrix, budget, min_distance=self.request.min_distance)
            for rank, index in enumerate(result.indices):
                name, frame = all_frames[int(index)]
                selected_pairs.append((frame, SelectionRecord(name, int(frame.source_index), frame.timestep, rank, result.distances[rank] if rank < len(result.distances) else None, 0)))
        else:
            rank = 0
            for name, frames in ordered:
                quota = quotas.get(name, 0)
                if quota <= 0:
                    continue
                matrix = self._describe(frames)
                result = centered_fps(matrix, quota, min_distance=self.request.min_distance)
                for local_rank, index in enumerate(result.indices):
                    frame = frames[int(index)]
                    distance = result.distances[local_rank] if local_rank < len(result.distances) else None
                    selected_pairs.append((frame, SelectionRecord(name, int(frame.source_index), frame.timestep, rank, distance, quota)))
                    rank += 1
        selected_pairs.sort(key=lambda pair: (self._source_order(pair[1].source_name), pair[1].source_index))
        output = write_outputs(selected_pairs, self.request.output_root, cache_root=self.request.cache_dir)
        state_path = Path(output["run_dir"]) / "run-state.json"
        state_path.write_text(json.dumps({"stage": "completed", "selected_count": len(selected_pairs)}, ensure_ascii=False, indent=2), encoding="utf-8")
        return RepresentativeSamplingResult(
            run_dir=Path(output["run_dir"]), selected_path=Path(output["selected_path"]),
            selection_path=Path(output["selection_path"]), summary_path=Path(output["summary_path"]),
            manifest_path=Path(output["manifest_path"]), selected_count=len(selected_pairs),
        )

    def _describe(self, frames: Sequence[FilterFrame]) -> np.ndarray:
        values = [np.asarray(self.descriptor.describe(frame), dtype=float).ravel() for frame in frames]
        if not values:
            return np.empty((0, 0))
        matrix = np.vstack(values)
        if not np.isfinite(matrix).all():
            raise ValueError("descriptor output must be finite")
        return matrix

    def _source_order(self, name: str) -> int:
        return next(index for index, source in enumerate(self.request.sources) if source.name == name)

