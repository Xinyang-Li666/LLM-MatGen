"""Chunked, deterministic farthest-point sampling."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np


@dataclass(frozen=True)
class FPSResult:
    indices: tuple[int, ...]
    distances: tuple[float | None, ...]
    stop_reason: Literal["count", "min_distance", "empty"]


def _point_distances(points: np.ndarray, point: np.ndarray, chunk_size: int) -> np.ndarray:
    result = np.empty(points.shape[0], dtype=np.float64)
    for start in range(0, points.shape[0], chunk_size):
        stop = min(start + chunk_size, points.shape[0])
        delta = points[start:stop] - point
        result[start:stop] = np.sqrt(np.einsum("ij,ij->i", delta, delta))
    return result


def _warm_distances(points: np.ndarray, warm_start: np.ndarray, chunk_size: int) -> np.ndarray:
    result = np.full(points.shape[0], np.inf, dtype=np.float64)
    for start in range(0, points.shape[0], chunk_size):
        stop = min(start + chunk_size, points.shape[0])
        delta = points[start:stop, None, :] - warm_start[None, :, :]
        distances = np.sqrt(np.sum(delta * delta, axis=2))
        result[start:stop] = np.min(distances, axis=1)
    return result


def centered_fps(
    points: np.ndarray,
    count: int,
    *,
    min_distance: float = 0.0,
    warm_start: np.ndarray | None = None,
    chunk_size: int = 8192,
) -> FPSResult:
    """Select points greedily from the center or an optional warm-start set."""

    values = np.asarray(points, dtype=np.float64)
    if values.ndim != 2:
        raise ValueError("points must be two-dimensional")
    if not np.all(np.isfinite(values)):
        raise ValueError("points must contain only finite values")
    if isinstance(count, bool) or int(count) != count or int(count) < 0:
        raise ValueError("count must be a non-negative integer")
    if not np.isfinite(min_distance) or float(min_distance) < 0:
        raise ValueError("min_distance must be finite and non-negative")
    if int(chunk_size) <= 0:
        raise ValueError("chunk_size must be positive")
    if values.shape[0] == 0 or count == 0:
        return FPSResult((), (), "empty")

    warm = None
    if warm_start is not None:
        warm = np.asarray(warm_start, dtype=np.float64)
        if warm.size == 0:
            warm = None
        else:
            if warm.ndim != 2 or warm.shape[1] != values.shape[1]:
                raise ValueError("warm-start dimensions must match points dimensions")
            if not np.all(np.isfinite(warm)):
                raise ValueError("warm-start points must contain only finite values")

    selected = np.zeros(values.shape[0], dtype=bool)
    indices: list[int] = []
    distances: list[float | None] = []
    if warm is not None:
        nearest = _warm_distances(values, warm, int(chunk_size))
    else:
        center = np.mean(values, axis=0)
        first = int(np.argmin(np.linalg.norm(values - center, axis=1)))
        indices.append(first)
        distances.append(None)
        selected[first] = True
        nearest = _point_distances(values, values[first], int(chunk_size))
        nearest[selected] = -np.inf

    target = min(int(count), values.shape[0])
    while len(indices) < target:
        candidate = int(np.argmax(nearest))
        candidate_distance = float(nearest[candidate])
        if selected[candidate] or not np.isfinite(candidate_distance):
            return FPSResult(tuple(indices), tuple(distances), "min_distance")
        if candidate_distance < float(min_distance):
            return FPSResult(tuple(indices), tuple(distances), "min_distance")
        indices.append(candidate)
        distances.append(candidate_distance)
        selected[candidate] = True
        nearest = np.minimum(
            nearest,
            _point_distances(values, values[candidate], int(chunk_size)),
        )
        nearest[selected] = -np.inf
    return FPSResult(tuple(indices), tuple(distances), "count")


def hierarchical_fps(
    points: np.ndarray,
    count: int,
    *,
    min_distance: float = 0.0,
    block_count: int = 64,
    chunk_size: int = 8192,
) -> FPSResult:
    """Approximate large FPS by deterministic contiguous trajectory blocks."""
    values = np.asarray(points)
    if values.ndim != 2:
        raise ValueError("points must be a two-dimensional array")
    if block_count <= 0:
        raise ValueError("block_count must be positive")
    if count <= 2048 or len(values) <= 4096 or block_count == 1:
        return centered_fps(values, count, min_distance=min_distance, chunk_size=chunk_size)
    blocks = [block for block in np.array_split(np.arange(len(values)), min(block_count, len(values))) if block.size]
    base, remainder = divmod(min(int(count), len(values)), len(blocks))
    selected: list[int] = []
    distances: list[float | None] = []
    stopped_early = False
    for block_index, block in enumerate(blocks):
        quota = base + int(block_index < remainder)
        if quota <= 0:
            continue
        result = centered_fps(
            values[block], min(quota, len(block)),
            min_distance=min_distance, chunk_size=chunk_size,
        )
        selected.extend(int(block[index]) for index in result.indices)
        distances.extend(result.distances)
        stopped_early = stopped_early or result.stop_reason != "count"
    return FPSResult(tuple(selected), tuple(distances), "min_distance" if stopped_early else "count")
