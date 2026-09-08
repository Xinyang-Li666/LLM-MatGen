"""Deterministic and streaming frame selection algorithms."""

from __future__ import annotations

import random
from collections.abc import Iterable, Iterator

from .models import TrajectoryFrame


def uniform_indices(total: int, count: int) -> list[int]:
    if total <= 0:
        raise ValueError("trajectory is empty")
    if count <= 0:
        raise ValueError("sample count must be positive")
    if count > total:
        raise ValueError(f"sample count {count} exceeds available frames {total}")
    if count == 1:
        return [total // 2]
    # Round to nearest integer while preserving endpoints and uniqueness.
    indices = [round(i * (total - 1) / (count - 1)) for i in range(count)]
    if len(set(indices)) != count:
        raise ValueError("sample count is too large for unique uniform frame indices")
    return indices


def random_indices(total: int, count: int, seed: int | None = None) -> list[int]:
    if total <= 0:
        raise ValueError("trajectory is empty")
    if count <= 0:
        raise ValueError("sample count must be positive")
    if count > total:
        raise ValueError(f"sample count {count} exceeds available frames {total}")
    rng = random.Random(seed)
    return sorted(rng.sample(range(total), count))


def reservoir_sample(frames: Iterable[TrajectoryFrame], count: int, seed: int | None = None) -> list[TrajectoryFrame]:
    if count <= 0:
        raise ValueError("sample count must be positive")
    rng = random.Random(seed)
    reservoir: list[TrajectoryFrame] = []
    for seen, frame in enumerate(frames):
        if seen < count:
            reservoir.append(frame)
        else:
            replacement = rng.randrange(seen + 1)
            if replacement < count:
                reservoir[replacement] = frame
    if not reservoir:
        raise ValueError("trajectory is empty")
    if len(reservoir) < count:
        raise ValueError(f"sample count {count} exceeds available frames {len(reservoir)}")
    return sorted(reservoir, key=lambda frame: frame.source_index)


def select_frames(reader, method: str, count: int | None = None, seed: int | None = None, stride: int = 1) -> list[TrajectoryFrame]:
    if stride <= 0:
        raise ValueError("stride must be positive")
    if method == "all":
        return [frame for frame in reader.iter_frames() if frame.source_index % stride == 0]
    if count is None:
        raise ValueError("count is required for uniform and random sampling")
    if method == "uniform":
        wanted = set(uniform_indices(reader.count_frames(), count))
        return [frame for frame in reader.iter_frames() if frame.source_index in wanted]
    if method == "random":
        return reservoir_sample(reader.iter_frames(), count, seed)
    raise ValueError(f"unsupported sampling method: {method}")
