from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from llm_matgen.trajectories.representative.config import ReductionConfig
from llm_matgen.trajectories.representative.reduction import reduce_descriptor_memmaps, reduce_descriptors


def test_reduction_is_deterministic_and_respects_dimension(tmp_path: Path):
    rng = np.random.default_rng(3)
    candidate = rng.normal(size=(20, 8))
    first = reduce_descriptors(candidate, tmp_path / "first.npy", ReductionConfig())
    second = reduce_descriptors(candidate, tmp_path / "second.npy", ReductionConfig())
    assert first.component_count <= 8
    assert first.component_count <= 19
    assert first.explained_variance_ratio >= 0.99
    np.testing.assert_allclose(np.load(first.output_path), np.load(second.output_path))


def test_candidate_and_existing_are_fit_together(tmp_path: Path):
    candidate = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]])
    existing = np.array([[100.0, 0.0], [101.0, 0.0]])
    result = reduce_descriptors(
        candidate,
        tmp_path / "out.npy",
        ReductionConfig(max_components=2, variance_target=0.99, fit_sample_count=4, seed=7),
        existing=existing,
    )
    assert result.fit_candidate_count + result.fit_existing_count == 4
    assert result.fit_existing_count >= 1
    assert np.load(result.output_path).shape[0] == len(candidate)


def test_single_frame_and_nonfinite_input(tmp_path: Path):
    result = reduce_descriptors(
        np.array([[1.0, 2.0]]), tmp_path / "single.npy", ReductionConfig()
    )
    assert result.component_count == 1
    assert np.all(np.load(result.output_path) == 0)
    with pytest.raises(ValueError, match="finite"):
        reduce_descriptors(np.array([[np.nan, 1.0], [0.0, 1.0]]), tmp_path / "bad.npy", ReductionConfig())


def test_missing_optional_dependency_has_install_hint(tmp_path: Path, monkeypatch):
    import builtins

    original = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name.startswith("sklearn"):
            raise ImportError("blocked")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(RuntimeError, match=r"llm-matgen\[fps\]"):
        reduce_descriptors(np.ones((3, 2)), tmp_path / "missing.npy", ReductionConfig())


def test_common_memmap_reduction_bounds_dimension(tmp_path: Path):
    rng = np.random.default_rng(19)
    first = np.memmap(tmp_path / "a.dat", mode="w+", dtype=np.float32, shape=(80, 96))
    second = np.memmap(tmp_path / "b.dat", mode="w+", dtype=np.float32, shape=(40, 96))
    first[:] = rng.normal(size=first.shape); second[:] = rng.normal(size=second.shape)
    reduced, metadata = reduce_descriptor_memmaps(
        {"a": first, "b": second}, tmp_path / "reduced",
        ReductionConfig(max_components=16, fit_sample_count=60),
    )
    assert reduced["a"].shape[1] <= 16
    assert reduced["a"].shape[1] == reduced["b"].shape[1]
    assert metadata.component_count <= 16
    assert np.isfinite(reduced["a"]).all()
