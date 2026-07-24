"""Validated immutable material snapshot contracts."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from uuid import UUID

from pydantic import BaseModel, Field, PositiveInt, RootModel, field_validator, model_validator

from llm_matgen.generators.models import JsonValue


def _require_finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("property numbers must be finite")
    if isinstance(value, dict):
        for item in value.values():
            _require_finite(item)
    elif isinstance(value, list):
        for item in value:
            _require_finite(item)


class PropertySet(RootModel[dict[str, JsonValue]]):
    @model_validator(mode="after")
    def validate_finite(self):
        _require_finite(self.root)
        return self


class MaterialSnapshot(BaseModel):
    snapshot_id: UUID
    material_id: str
    source_db_version: str | None = None
    structure_hash: str | None = None
    formula: str
    elements: list[str] = Field(min_length=1)
    n_elements: PositiveInt
    properties: PropertySet = Field(default_factory=lambda: PropertySet({}))
    property_origins: dict[str, str] = Field(default_factory=dict)
    raw_json: dict[str, JsonValue] | None = None
    fetched_at: datetime

    @field_validator("elements")
    @classmethod
    def normalize_elements(cls, value: list[str]) -> list[str]:
        return sorted(set(value))

    @field_validator("fetched_at")
    @classmethod
    def normalize_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("fetched_at must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_element_count(self):
        if self.n_elements != len(self.elements):
            raise ValueError("n_elements must equal the number of unique elements")
        _require_finite(self.raw_json)
        return self


class LocalMaterialQuery(BaseModel):
    elements: list[str] | None = None
    n_elements: PositiveInt | None = None
    band_gap_min: float | None = None
    band_gap_max: float | None = None
    formation_energy_max: float | None = None
    formula_pattern: str | None = None
    limit: PositiveInt = 100
    all_snapshots: bool = False

    @model_validator(mode="after")
    def validate_ranges(self):
        if (
            self.band_gap_min is not None
            and self.band_gap_max is not None
            and self.band_gap_min > self.band_gap_max
        ):
            raise ValueError("band gap minimum cannot exceed maximum")
        for value in (self.band_gap_min, self.band_gap_max, self.formation_energy_max):
            if value is not None and not math.isfinite(value):
                raise ValueError("query numbers must be finite")
        if self.elements is not None:
            self.elements = sorted(set(self.elements))
        return self
