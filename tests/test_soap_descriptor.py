from __future__ import annotations

import numpy as np
import pytest

from llm_matgen.trajectories.filtering.models import FilterFrame
from llm_matgen.trajectories.representative.config import SOAPConfig
from llm_matgen.trajectories.representative.soap import SOAPDescriptorBackend


def frame(numbers=(22, 5, 8), shift=(0, 0, 0), positions=None):
    return FilterFrame(
        np.array(numbers), (np.array([[0, 0, 0], [1.6, 0, 0], [0, 1.6, 0]], float) if positions is None else np.asarray(positions, float)) + shift,
        np.array([[5., .2, 0], [0, 5., .1], [0, 0, 5.]]), np.array([True] * 3),
    )


def test_periodic_soap_is_invariant_and_float32():
    config = SOAPConfig(r_cut=2.5, n_max=2, l_max=2, sigma=0.4)
    backend = SOAPDescriptorBackend((5, 8, 22), config)
    first = backend.describe_local(frame())
    second = backend.describe_local(frame(numbers=(8, 5, 22), positions=[[0, 1.6, 0], [1.6, 0, 0], [0, 0, 0]], shift=(1.0, 2.0, 0.5)))
    assert first.dtype == np.float32
    assert first.shape == second.shape
    assert np.isfinite(first).all()
    np.testing.assert_allclose(np.sort(first, axis=0), np.sort(second, axis=0), atol=1e-5)


def test_species_outside_config_is_rejected():
    backend = SOAPDescriptorBackend((5, 22), SOAPConfig(r_cut=2.5, n_max=2, l_max=1))
    with pytest.raises(ValueError, match="species"):
        backend.describe_local(frame())
