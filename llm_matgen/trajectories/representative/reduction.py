"""Optional, deterministic dimensionality reduction for descriptors."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import ReductionConfig


@dataclass(frozen=True)
class ReductionResult:
    output_path: Path
    component_count: int
    explained_variance_ratio: float
    fit_candidate_count: int
    fit_existing_count: int
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class MemmapReductionMetadata:
    component_count: int
    explained_variance_ratio: float
    fit_sample_count: int


def reduce_descriptors(
    candidate: np.ndarray,
    output_path: Path,
    config: ReductionConfig,
    *,
    existing: np.ndarray | None = None,
) -> ReductionResult:
    candidate = _validate(candidate, "candidate")
    if existing is not None:
        existing = _validate(existing, "existing")
        if existing.shape[1] != candidate.shape[1]:
            raise ValueError("candidate and existing feature dimensions must match")
    if candidate.shape[0] == 1:
        result = np.zeros((1, 1), dtype=np.float32)
        _save(result, output_path)
        return ReductionResult(Path(output_path), 1, 1.0, 1, 0, ("single_frame_zero_vector",))

    try:
        from sklearn.decomposition import PCA
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        raise RuntimeError("install optional dependency with `pip install llm-matgen[fps]`") from exc

    existing = np.empty((0, candidate.shape[1]), dtype=float) if existing is None else existing
    fit_candidate_count, fit_existing_count = _fit_counts(
        len(candidate), len(existing), config.fit_sample_count
    )
    candidate_idx = _sample_indices(len(candidate), fit_candidate_count, config.seed)
    existing_idx = _sample_indices(len(existing), fit_existing_count, config.seed + 1)
    fit = np.vstack((candidate[candidate_idx], existing[existing_idx]))
    scaler = StandardScaler(with_mean=True, with_std=True)
    fit_scaled = scaler.fit_transform(fit)
    max_components = min(config.max_components, fit_scaled.shape[0] - 1, fit_scaled.shape[1])
    if max_components <= 0:
        transformed = np.zeros((len(candidate), 1), dtype=np.float32)
        _save(transformed, output_path)
        return ReductionResult(Path(output_path), 1, 1.0, fit_candidate_count, fit_existing_count, ("low_rank_zero_vector",))
    pca = PCA(n_components=max_components, svd_solver="randomized", random_state=config.seed, whiten=config.whiten)
    pca.fit(fit_scaled)
    cumulative = np.cumsum(pca.explained_variance_ratio_)
    component_count = int(np.searchsorted(cumulative, config.variance_target, side="left") + 1)
    component_count = max(1, min(component_count, max_components))
    transformed = pca.transform(scaler.transform(candidate))[:, :component_count].astype(np.float32)
    _save(transformed, output_path)
    return ReductionResult(
        Path(output_path), component_count, float(cumulative[component_count - 1]),
        fit_candidate_count, fit_existing_count,
    )


def reduce_descriptor_memmaps(
    matrices: dict[str, np.memmap],
    output_dir: Path,
    config: ReductionConfig,
    *,
    transform_chunk_size: int = 2048,
) -> tuple[dict[str, np.memmap], MemmapReductionMetadata]:
    """Fit one scaler/PCA on deterministic samples and transform memmaps by chunk."""
    if not matrices:
        raise ValueError("at least one descriptor matrix is required")
    try:
        from sklearn.decomposition import PCA
        from sklearn.preprocessing import StandardScaler
    except ImportError as exc:
        raise RuntimeError("install optional dependency with `pip install llm-matgen[fps]`") from exc
    feature_counts = {matrix.shape[1] for matrix in matrices.values()}
    if len(feature_counts) != 1:
        raise ValueError("all descriptor matrices must share the same feature dimension")
    total = sum(len(matrix) for matrix in matrices.values())
    fit_budget = min(config.fit_sample_count, total)
    samples: list[np.ndarray] = []
    assigned = 0
    items = list(matrices.items())
    for index, (_, matrix) in enumerate(items):
        if index == len(items) - 1:
            quota = fit_budget - assigned
        else:
            quota = min(len(matrix), max(1, round(fit_budget * len(matrix) / total)))
            assigned += quota
        indices = np.linspace(0, len(matrix) - 1, min(quota, len(matrix)), dtype=int)
        samples.append(np.asarray(matrix[indices], dtype=np.float32))
    fit = np.vstack(samples)
    scaler = StandardScaler(copy=False)
    fit_scaled = scaler.fit_transform(fit)
    max_components = min(config.max_components, fit_scaled.shape[0] - 1, fit_scaled.shape[1])
    if max_components <= 0:
        component_count = 1
        explained = 1.0
        pca = None
    else:
        pca = PCA(n_components=max_components, svd_solver="randomized", random_state=config.seed, whiten=config.whiten)
        pca.fit(fit_scaled)
        cumulative = np.cumsum(pca.explained_variance_ratio_)
        component_count = min(max_components, int(np.searchsorted(cumulative, config.variance_target) + 1))
        explained = float(cumulative[component_count - 1])
    output_dir = Path(output_dir); output_dir.mkdir(parents=True, exist_ok=True)
    reduced: dict[str, np.memmap] = {}
    for name, matrix in matrices.items():
        target = np.memmap(output_dir / f"{name}.reduced.dat", mode="w+", dtype=np.float32, shape=(len(matrix), component_count))
        for start in range(0, len(matrix), transform_chunk_size):
            stop = min(start + transform_chunk_size, len(matrix))
            scaled = scaler.transform(np.asarray(matrix[start:stop], dtype=np.float32))
            target[start:stop] = 0.0 if pca is None else pca.transform(scaled)[:, :component_count]
        target.flush(); reduced[name] = target
    return reduced, MemmapReductionMetadata(component_count, explained, len(fit))


def _validate(array: np.ndarray, label: str) -> np.ndarray:
    values = np.asarray(array, dtype=float)
    if values.ndim != 2 or values.shape[0] == 0 or values.shape[1] == 0:
        raise ValueError(f"{label} descriptors must be a non-empty 2D array")
    if not np.isfinite(values).all():
        raise ValueError(f"{label} descriptors must be finite")
    return values


def _fit_counts(candidate_count: int, existing_count: int, limit: int) -> tuple[int, int]:
    total = candidate_count + existing_count
    budget = min(total, int(limit))
    if existing_count == 0:
        return budget, 0
    if candidate_count == 0:
        return 0, budget
    if budget <= 1:
        return 1, 0
    candidate_fit = max(1, int(budget * candidate_count / total))
    existing_fit = budget - candidate_fit
    if existing_fit == 0:
        existing_fit, candidate_fit = 1, budget - 1
    return candidate_fit, existing_fit


def _sample_indices(size: int, count: int, seed: int) -> np.ndarray:
    if count <= 0:
        return np.empty(0, dtype=int)
    if count >= size:
        return np.arange(size)
    return np.sort(np.random.default_rng(seed).choice(size, size=count, replace=False))


def _save(array: np.ndarray, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, array)
