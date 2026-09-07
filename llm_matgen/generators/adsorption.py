"""Contracts shared by adsorption proposal, validation and generation stages.

The models in this module deliberately contain no generation policy.  They are
the small, serialisable boundary between a slab/molecule input, configurable
sampling limits, and the information handed to a downstream DFT workflow.
"""

from __future__ import annotations

import math
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt, field_validator, model_validator
from pymatgen.core import Molecule, Structure


class _AdsorptionModel(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", frozen=True)


class AdsorptionInput(_AdsorptionModel):
    """A slab and an adsorbate with a CLI-facing, one-based anchor index."""

    slab: Structure
    molecule: Molecule | Structure
    anchor_index: PositiveInt = Field(description="One-based atom index in the adsorbate")

    @model_validator(mode="after")
    def validate_input(self) -> "AdsorptionInput":
        if len(self.slab) == 0 or len(self.molecule) == 0:
            raise ValueError("slab and molecule must contain at least one atom")
        if self.anchor_index > len(self.molecule):
            raise ValueError("anchor_index is outside the adsorbate")
        coords = np.asarray(self.molecule.cart_coords, dtype=float)
        if not np.isfinite(coords).all():
            raise ValueError("molecule coordinates must be finite")
        return self

    @property
    def anchor_index_zero_based(self) -> int:
        return self.anchor_index - 1


class AdsorptionParams(_AdsorptionModel):
    """Bounded generation controls; all counts are intentionally finite."""

    site_height: PositiveFloat = 2.0
    max_structures: PositiveInt = 1000
    max_atoms_per_structure: PositiveInt = 10000
    history_mode: Literal["off", "prefer", "require"] = "off"
    site_kinds: tuple[str, ...] = ("ontop", "bridge", "hollow")
    surface_side: Literal["top", "bottom", "both"] = "top"
    fixed_bottom_layers: int = Field(default=0, ge=0)

    @field_validator("site_height")
    @classmethod
    def finite_height(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("site_height must be finite")
        return value


class DFTHandoffMatrix(_AdsorptionModel):
    """Explicit handoff metadata so DFT setup assumptions are not implicit."""

    matrix: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]
    vacuum_axis: int = Field(default=2, ge=0, le=2)
    notes: tuple[str, ...] = ()

    @field_validator("matrix")
    @classmethod
    def valid_matrix(cls, value: Any):
        array = np.asarray(value, dtype=float)
        if array.shape != (3, 3) or not np.isfinite(array).all():
            raise ValueError("matrix must be a finite 3x3 matrix")
        if abs(float(np.linalg.det(array))) < 1e-12:
            raise ValueError("matrix must be nonsingular")
        return tuple(tuple(float(component) for component in row) for row in array)


class AdsorptionGenerationResult(_AdsorptionModel):
    """Stable result envelope used by later generator and pipeline stages."""

    generated: tuple[Structure, ...] = ()
    warnings: tuple[str, ...] = ()
    dft_handoff: DFTHandoffMatrix | None = None
    actual_parameters: dict[str, Any] = Field(default_factory=dict)

