from __future__ import annotations

import numpy as np

from llm_matgen.trajectories.representative.soap import pool_local_soap


def test_category_mean_std_preserves_category_variance_and_presence():
    local = np.array([[1., 0.], [3., 0.], [2., 2.], [9., 9.]])
    numbers = np.array([22, 23, 5, 8])
    result = pool_local_soap(local, numbers, {"TM": (22, 23), "B": (5,), "O": (8,)})
    assert result.values.shape == (15,)  # 3 categories * (mean + std) * 2 + masks
    assert result.values[0] == 2 and result.values[2] == 1
    assert result.values[-3:].tolist() == [1.0, 1.0, 1.0]
    assert result.names[0].startswith("TM:mean:")


def test_missing_category_is_zero_and_singleton_std_is_finite():
    result = pool_local_soap(np.array([[4., 5.]]), np.array([5]), {"TM": (22,), "B": (5,), "O": (8,)})
    assert np.all(result.values[:4] == 0)
    assert result.values[4] == 4 and result.values[6] == 0
    assert result.values[-3:].tolist() == [0.0, 1.0, 0.0]
