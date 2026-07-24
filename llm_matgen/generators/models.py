"""Public data contracts shared by generators and execution adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, TypeAlias, Union
from typing_extensions import TypeAliasType

from pydantic import BaseModel, ConfigDict, Field, PositiveInt

JsonPrimitive: TypeAlias = None | bool | int | float | str
JsonValue = TypeAliasType(
    "JsonValue",
    Union[JsonPrimitive, list["JsonValue"], dict[str, "JsonValue"]],
)


class OutputFormat(str, Enum):
    POSCAR = "poscar"
    CIF = "cif"
    LAMMPS_DATA = "lammps-data"


class CheckLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class BaseGenerationParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_structures: PositiveInt = 1000


class RandomGenerationParams(BaseGenerationParams):
    seed: int | None = None


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generator: str
    generator_version: str
    input_source: str
    input_structure_hash: str
    parameters: dict[str, JsonValue]
    seed: int | None
    created_at: datetime


class StructureRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    structure_id: str
    parent_structure_id: str
    formula: str
    n_atoms: PositiveInt
    actual_parameters: dict[str, JsonValue]
    site_mapping: dict[str, str | None]


@dataclass
class GeneratedStructure:
    structure: Any
    record: StructureRecord


@dataclass
class GenerationResult:
    defect_type: str = ""
    input_count: int = 0
    skipped_count: int = 0
    generated: list[GeneratedStructure] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    provenance: Provenance | None = None

    @property
    def generated_count(self) -> int:
        return len(self.generated)

    def combine(self, other: "GenerationResult") -> "GenerationResult":
        if self.defect_type != other.defect_type:
            raise ValueError("cannot combine results with different defect_type")
        return GenerationResult(
            defect_type=self.defect_type,
            input_count=self.input_count + other.input_count,
            skipped_count=self.skipped_count + other.skipped_count,
            generated=[*self.generated, *other.generated],
            warnings=[*self.warnings, *other.warnings],
            provenance=self.provenance or other.provenance,
        )
