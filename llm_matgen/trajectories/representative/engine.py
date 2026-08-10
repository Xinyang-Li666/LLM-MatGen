"""In-memory orchestration for representative FPS sampling."""

from __future__ import annotations

import json
import tempfile
import shutil
from pathlib import Path
from typing import Callable, Iterator, Mapping, Sequence

import numpy as np

from llm_matgen.trajectories.filtering.models import FilterFrame
from .fps import centered_fps
from .models import RepresentativeSamplingRequest, RepresentativeSamplingResult, SelectionRecord
from .quotas import allocate_proportional_quotas
from .writers import write_outputs, write_outputs_streaming


class RepresentativeSamplingEngine:
    def __init__(self, request: RepresentativeSamplingRequest, descriptor):
        if request.method not in {"rdf-fps", "soap-fps"}:
            raise ValueError(f"unsupported sampling method: {request.method}")
        self.request = request
        self.descriptor = descriptor

    def run(self, frames_by_source: Mapping[str, Sequence[FilterFrame]], *, warm_start: np.ndarray | Mapping[str, np.ndarray] | None = None) -> RepresentativeSamplingResult:
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
            result = centered_fps(matrix, budget, min_distance=self.request.min_distance, warm_start=warm_start if isinstance(warm_start, np.ndarray) else None)
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
                initial = warm_start.get(name) if isinstance(warm_start, Mapping) else None
                result = centered_fps(matrix, quota, min_distance=self.request.min_distance, warm_start=initial)
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

    def run_streaming(
        self,
        source_factories: Mapping[str, Callable[[], Iterator[FilterFrame]]],
        source_counts: Mapping[str, int],
    ) -> RepresentativeSamplingResult:
        """Run descriptor/FPS/export in bounded memory using per-source memmaps."""
        counts = {name: int(source_counts.get(name, 0)) for name in (spec.name for spec in self.request.sources)}
        total = sum(counts.values())
        if total == 0:
            raise ValueError("no candidate frames were provided")
        budget = min(self.request.count, total)
        quotas = allocate_proportional_quotas(counts, budget) if self.request.allocation == "proportional" else {name: 0 for name in counts}
        temp_root = self.request.output_root / ".descriptor-work"
        temp_root.mkdir(parents=True, exist_ok=True)
        selected_by_source: dict[str, tuple[set[int], tuple[float | None, ...]]] = {}
        try:
            matrices: dict[str, np.memmap] = {}
            for spec in self.request.sources:
                name = spec.name
                n = counts[name]
                if n <= 0:
                    continue
                iterator = source_factories[name]()
                try:
                    first = next(iterator)
                except StopIteration:
                    continue
                first_vector = np.asarray(self.descriptor.describe(first), dtype=np.float32).ravel()
                if first_vector.size == 0 or not np.isfinite(first_vector).all():
                    raise ValueError("descriptor output must be finite and non-empty")
                path = temp_root / f"{name}.dat"
                matrix = np.memmap(path, mode="w+", dtype=np.float32, shape=(n, first_vector.size))
                matrix[0] = first_vector
                position = 1
                for frame in iterator:
                    vector = np.asarray(self.descriptor.describe(frame), dtype=np.float32).ravel()
                    if vector.shape != (first_vector.size,) or not np.isfinite(vector).all():
                        raise ValueError(f"descriptor shape/value mismatch in source {name}")
                    if position >= n:
                        raise ValueError(f"source {name} yielded more frames than inventory")
                    matrix[position] = vector
                    position += 1
                if position != n:
                    raise ValueError(f"source {name} yielded {position} frames, expected {n}")
                matrix.flush()
                matrices[name] = matrix
                quota = quotas.get(name, 0)
                if self.request.allocation == "global":
                    continue
                fps_result = centered_fps(matrix, quota, min_distance=self.request.min_distance)
                selected_by_source[name] = (set(int(index) for index in fps_result.indices), fps_result.distances)
            if self.request.allocation == "global":
                names = [spec.name for spec in self.request.sources if counts[spec.name] > 0]
                combined = np.concatenate([np.asarray(matrices[name]) for name in names], axis=0)
                fps_result = centered_fps(combined, budget, min_distance=self.request.min_distance)
                offsets = np.cumsum([0] + [counts[name] for name in names])
                selected_by_source = {name: (set(), ()) for name in names}
                for index, distance in zip(fps_result.indices, fps_result.distances):
                    group = int(np.searchsorted(offsets, int(index), side="right") - 1)
                    selected_by_source[names[group]][0].add(int(index) - int(offsets[group]))
            def selected_stream():
                rank = 0
                for spec in self.request.sources:
                    name = spec.name
                    selected, distances = selected_by_source.get(name, (set(), ()))
                    if not selected:
                        continue
                    distance_by_index = {index: distances[pos] if pos < len(distances) else None for pos, index in enumerate(sorted(selected))}
                    for index, frame in enumerate(source_factories[name]()):
                        if index in selected:
                            yield frame, SelectionRecord(name, int(frame.source_index), frame.timestep, rank, distance_by_index.get(index), quotas.get(name, 0))
                            rank += 1
            output = write_outputs_streaming(selected_stream(), self.request.output_root, cache_root=self.request.cache_dir)
            state_path = Path(output["run_dir"]) / "run-state.json"
            selected_count = int(output["selected_count"])
            state_path.write_text(json.dumps({"stage": "completed", "selected_count": selected_count, "streaming": True}, ensure_ascii=False, indent=2), encoding="utf-8")
            return RepresentativeSamplingResult(Path(output["run_dir"]), Path(output["selected_path"]), Path(output["selection_path"]), Path(output["summary_path"]), Path(output["manifest_path"]), selected_count)
        finally:
            for matrix in locals().get("matrices", {}).values():
                mmap_handle = getattr(matrix, "_mmap", None)
                if mmap_handle is not None:
                    mmap_handle.close()
            shutil.rmtree(temp_root, ignore_errors=True)

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
