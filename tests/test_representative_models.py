from pathlib import Path

import pytest

from llm_matgen.trajectories.representative.config import (
    RDFSamplingConfig,
    merge_sampling_config,
)
from llm_matgen.trajectories.representative.models import (
    RepresentativeSamplingRequest,
    SourceSpec,
)


def test_source_spec_and_request_validate_required_values():
    source = SourceSpec(name="A", path=Path("a.extxyz"))
    request = RepresentativeSamplingRequest(
        sources=(source,), method="rdf-fps", count=2,
    )
    assert request.sources == (source,)
    assert request.count == 2
    assert request.allocation == "proportional"

    with pytest.raises(ValueError, match="source name"):
        SourceSpec(name="", path=Path("a.extxyz"))
    with pytest.raises(ValueError, match="count"):
        RepresentativeSamplingRequest(sources=(source,), method="rdf-fps", count=0)
    with pytest.raises(ValueError, match="min_distance"):
        RepresentativeSamplingRequest(
            sources=(source,), method="rdf-fps", count=2, min_distance=-1,
        )


def test_request_rejects_duplicate_sources_and_invalid_modes():
    first = SourceSpec(name="A", path=Path("a.extxyz"))
    second = SourceSpec(name="A", path=Path("b.extxyz"))
    with pytest.raises(ValueError, match="duplicate"):
        RepresentativeSamplingRequest(
            sources=(first, second), method="rdf-fps", count=2,
        )
    with pytest.raises(ValueError, match="allocation"):
        RepresentativeSamplingRequest(
            sources=(first,), method="rdf-fps", count=2, allocation="sqrt",
        )
    with pytest.raises(ValueError, match="method"):
        RepresentativeSamplingRequest(
            sources=(first,), method="random", count=2,
        )


def test_rdf_config_defaults_and_cli_overrides_are_deterministic():
    base = RDFSamplingConfig.from_dict({"r_max": 5.0, "reduction": {"max_components": 32}})
    merged = merge_sampling_config(
        base,
        {"r_max": 6.0, "reduction": {"max_components": 64}},
    )
    assert base.r_min == 0.8
    assert base.bin_width == 0.05
    assert base.reduction.max_components == 32
    assert merged.r_max == 6.0
    assert merged.reduction.max_components == 64


def test_rdf_config_rejects_invalid_values():
    with pytest.raises(ValueError, match="r_max"):
        RDFSamplingConfig.from_dict({"r_min": 4.0, "r_max": 3.0})
    with pytest.raises(ValueError, match="profile"):
        RDFSamplingConfig.from_dict({"profile": "unknown"})
