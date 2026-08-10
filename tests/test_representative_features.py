from __future__ import annotations

import numpy as np

from llm_matgen.trajectories.filtering.models import FilterFrame
from llm_matgen.trajectories.representative.features import (
    FeatureSchema,
    RDFFeaturePipeline,
    infer_coordination_cutoff,
)
from llm_matgen.trajectories.representative.rdf import RDFChannel, RDFDescriptor


def make_frame(scale: float = 1.0) -> FilterFrame:
    return FilterFrame(
        atomic_numbers=np.array([22, 5, 5]),
        positions=np.array([[0, 0, 0], [scale, 0, 0], [2 * scale, 0, 0]], float),
        cell=np.diag([6.0, 6.0, 6.0]), pbc=np.array([True, True, True]),
    )


def test_pipeline_fit_transform_and_weighted_blocks():
    rdf = RDFDescriptor((RDFChannel("Ti-B", (22,), (5,)),), 0.0, 3.0, 1.0)
    pipeline = RDFFeaturePipeline(rdf, coordination_cutoff=2.5, weights=(0.65, 0.25, 0.10))
    schema = pipeline.fit([make_frame(1.0), make_frame(1.2), make_frame(1.4)])
    values = pipeline.transform(make_frame(1.1))
    assert isinstance(schema, FeatureSchema)
    assert values.shape == (len(schema.names),)
    assert schema.blocks.count("rdf") == len(rdf.feature_names)
    assert np.isfinite(values).all()
    assert any(not active for active in schema.active)  # constant cell fields are inactive


def test_explicit_cutoff_has_priority_and_fallback_emits_warning():
    cutoff, warning = infer_coordination_cutoff(np.array([0.9, 1.0, 1.1, 2.0]), explicit=1.5)
    assert cutoff == 1.5 and warning is None
    cutoff, warning = infer_coordination_cutoff(np.array([1.0, 1.1, 1.2]), explicit=None)
    assert cutoff > 0 and warning is not None

