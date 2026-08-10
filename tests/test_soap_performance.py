from __future__ import annotations

import time

import numpy as np
import pytest

from llm_matgen.trajectories.representative.soap import pool_local_soap


@pytest.mark.performance
def test_category_pooling_scales_linearly_with_frame_count():
    rng = np.random.default_rng(5)
    groups = {"TM": (22,), "B": (5,), "O": (8,)}
    timings = []
    for count in (100, 1000):
        local = rng.normal(size=(count, 16)).astype(np.float32)
        numbers = np.resize(np.array([22, 5, 8]), count)
        start = time.perf_counter()
        result = pool_local_soap(local, numbers, groups)
        timings.append(time.perf_counter() - start)
        assert result.values.size == 3 * 16 * 2 + 3
    assert timings[1] < timings[0] * 30 + 1.0

