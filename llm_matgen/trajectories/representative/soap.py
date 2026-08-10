"""DScribe SOAP backend (optional dependency)."""

from __future__ import annotations

from typing import Iterable

import numpy as np

from llm_matgen.trajectories.filtering.models import FilterFrame
from .config import SOAPConfig


class SOAPDescriptorBackend:
    def __init__(self, species: Iterable[int], config: SOAPConfig | None = None):
        try:
            from dscribe.descriptors import SOAP  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("install optional dependency with `pip install llm-matgen[soap]`") from exc
        self.species = tuple(sorted({int(z) for z in species}))
        self.config = config or SOAPConfig()

    def describe_local(self, frame: FilterFrame) -> np.ndarray:
        raise NotImplementedError("DScribe SOAP descriptor construction is implemented in the next SOAP task")

