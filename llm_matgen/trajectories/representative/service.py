"""Public service facade for representative trajectory sampling."""

from __future__ import annotations

from typing import Mapping, Sequence

from llm_matgen.trajectories.filtering.models import FilterFrame
from .engine import RepresentativeSamplingEngine
from .models import RepresentativeSamplingRequest, RepresentativeSamplingResult


def sample_representative(
    request: RepresentativeSamplingRequest,
    descriptor,
    frames_by_source: Mapping[str, Sequence[FilterFrame]],
) -> RepresentativeSamplingResult:
    return RepresentativeSamplingEngine(request, descriptor).run(frames_by_source)

