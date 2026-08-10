import numpy as np
import pytest

from llm_matgen.trajectories.representative.fps import centered_fps


def test_centered_fps_is_deterministic_unique_and_starts_at_center():
    points = np.asarray([[0.0], [4.0], [5.0], [6.0], [10.0]], dtype=np.float32)

    first = centered_fps(points, 3)
    assert first.indices == (2, 0, 4)
    assert first.indices == centered_fps(points, 3).indices
    assert len(set(first.indices)) == 3
    assert first.stop_reason == "count"


def test_centered_fps_respects_min_distance_and_duplicate_points():
    points = np.zeros((4, 2), dtype=np.float32)

    assert len(centered_fps(points, 4, min_distance=0.1).indices) == 1
    assert len(centered_fps(points, 4, min_distance=0.0).indices) == 4


def test_centered_fps_uses_warm_start_and_records_distances():
    points = np.asarray([[0.0], [0.2], [2.0]], dtype=np.float32)
    result = centered_fps(
        points, 2, min_distance=0.5, warm_start=np.asarray([[0.0]], dtype=np.float32),
    )
    assert result.indices == (2,)
    assert result.distances == (2.0,)
    assert result.stop_reason == "min_distance"


def test_centered_fps_chunk_size_does_not_change_selection():
    points = np.random.default_rng(42).normal(size=(25, 4)).astype(np.float32)
    assert centered_fps(points, 10, chunk_size=3).indices == centered_fps(
        points, 10, chunk_size=64,
    ).indices


def test_centered_fps_rejects_invalid_inputs():
    with pytest.raises(ValueError, match="two-dimensional"):
        centered_fps(np.zeros(3), 1)
    with pytest.raises(ValueError, match="finite"):
        centered_fps(np.asarray([[np.nan]]), 1)
    with pytest.raises(ValueError, match="dimensions"):
        centered_fps(np.zeros((2, 1)), 1, warm_start=np.zeros((1, 2)))
