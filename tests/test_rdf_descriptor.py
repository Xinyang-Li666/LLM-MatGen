from __future__ import annotations

import numpy as np
import pytest

from llm_matgen.trajectories.filtering.models import FilterFrame
from llm_matgen.trajectories.representative.rdf import RDFChannel, RDFDescriptor, build_hybrid_channels


def frame(numbers=(22, 5, 5), positions=None, cell=None, pbc=None):
    if positions is None:
        positions = np.array([[0, 0, 0], [1.0, 0, 0], [2.0, 0, 0]], float)
    if cell is None:
        cell = np.diag([6.0, 6.0, 6.0])
    return FilterFrame(
        atomic_numbers=np.array(numbers), positions=np.asarray(positions),
        cell=cell, pbc=np.array([True, True, True] if pbc is None else pbc),
    )


def test_descriptor_is_invariant_to_translation_rotation_and_atom_order():
    descriptor = RDFDescriptor((RDFChannel("Ti-B", (22,), (5,)),), 0.0, 3.0, 1.0)
    base = frame()
    transformed = frame(
        numbers=(5, 5, 22),
        positions=np.array([[2, 1, 0], [2, 2, 0], [2, 0, 0]], float),
    )
    np.testing.assert_allclose(descriptor.describe(base), descriptor.describe(transformed))


def test_bin_is_left_closed_right_open_and_same_species_not_double_counted():
    channel = RDFChannel("B-B", (5,), (5,))
    descriptor = RDFDescriptor((channel,), 0.0, 3.0, 1.0)
    values = descriptor.describe(frame())
    assert values.shape == (3,)
    assert values[1] > 0  # distance exactly 1 belongs to [1, 2)
    assert values[2] == 0


def test_empty_channel_and_invalid_values():
    descriptor = RDFDescriptor((RDFChannel("O-O", (8,), (8,)),), 0.0, 3.0, 1.0)
    assert np.all(descriptor.describe(frame()) == 0)
    with pytest.raises(ValueError):
        RDFDescriptor((), 2.0, 1.0, 0.1)
    with pytest.raises(ValueError):
        descriptor.describe(frame(positions=np.array([[np.nan, 0, 0], [1, 0, 0], [2, 0, 0]])))


def test_feature_names_and_hybrid_channels():
    channels = build_hybrid_channels((22, 5, 8))
    assert any(channel.left == (5,) and channel.right == (22,) for channel in channels)
    descriptor = RDFDescriptor(channels, 0.5, 2.5, 0.5)
    assert len(descriptor.feature_names) == len(channels) * 4


def test_small_fully_periodic_frame_uses_vectorized_neighbor_path(monkeypatch):
    import llm_matgen.trajectories.representative.rdf as rdf_module

    def forbidden(*args, **kwargs):
        raise AssertionError("ASE neighbor list fallback should not be used")

    monkeypatch.setattr(rdf_module, "neighbor_list", forbidden)
    descriptor = RDFDescriptor((RDFChannel("Ti-B", (22,), (5,)),), 0.0, 3.0, 1.0)
    assert np.isfinite(descriptor.describe(frame())).all()
