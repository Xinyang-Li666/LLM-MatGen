"""Streaming trajectory readers, samplers, filters, and series exporters."""

from .filter import FilterConfig, FilterResult, filter_trajectory
from .models import SamplingMethod, TrajectoryFrame
from .sampling import random_indices, uniform_indices
from .filtering import FilterFrame
from .filtering.config import FilterConfig as TrajectoryFilterConfig
from .filtering.engine import FilterEngine, FilterRunResult
from .filtering.service import TrajectoryFilterService
from .representative import RepresentativeSamplingEngine, sample_representative

__all__ = [
    "FilterConfig",
    "FilterResult",
    "SamplingMethod",
    "TrajectoryFrame",
    "filter_trajectory",
    "random_indices",
    "uniform_indices",
    "FilterFrame",
    "TrajectoryFilterConfig",
    "FilterEngine",
    "FilterRunResult",
    "TrajectoryFilterService",
    "RepresentativeSamplingEngine",
    "sample_representative",
]
