"""Two-parent contracts for coherent interface generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic import Field, NonNegativeFloat, PositiveFloat, field_validator
from pymatgen.core import Structure

from llm_matgen.generators.backends import InterfaceMatcherBackend, PymatgenInterfaceMatcherBackend
from llm_matgen.generators.extended import MillerIndex, normalize_miller
from llm_matgen.generators.models import (
    BaseGenerationParams,
    GeneratedStructure,
    GenerationResult,
    Provenance,
    StructureRecord,
)
from llm_matgen.utils.structure import assign_site_ids, structure_sha256


@dataclass(frozen=True)
class InterfaceInput:
    film: Structure
    substrate: Structure


@dataclass(frozen=True)
class BinaryLineage:
    parent_structure_ids: dict[str, str]
    site_mapping: dict[str, str | None]


def build_binary_lineage(inputs: InterfaceInput) -> BinaryLineage:
    film_id = structure_sha256(inputs.film)
    substrate_id = structure_sha256(inputs.substrate)
    mapping: dict[str, str | None] = {}
    for site_id in assign_site_ids(inputs.film, film_id):
        mapping[f"film:{site_id}"] = None
    for site_id in assign_site_ids(inputs.substrate, substrate_id):
        mapping[f"substrate:{site_id}"] = None
    return BinaryLineage(
        parent_structure_ids={"film": film_id, "substrate": substrate_id},
        site_mapping=mapping,
    )


class InterfaceParams(BaseGenerationParams):
    film_millers: list[MillerIndex] = Field(min_length=1)
    substrate_millers: list[MillerIndex] = Field(min_length=1)
    film_thickness: PositiveFloat
    substrate_thickness: PositiveFloat
    vacuum_thickness: NonNegativeFloat
    gap: NonNegativeFloat
    max_area: PositiveFloat
    max_area_ratio_tol: PositiveFloat
    max_length_tol: PositiveFloat
    max_angle_tol: PositiveFloat

    @field_validator("film_millers", "substrate_millers")
    @classmethod
    def validate_millers(cls, value: list[MillerIndex]) -> list[MillerIndex]:
        return list(dict.fromkeys(normalize_miller(index) for index in value))


class InterfaceGenerator:
    defect_name = "interface"
    generator_version = "0.1.0"

    def __init__(self, backend: InterfaceMatcherBackend | None = None):
        self.backend = backend or PymatgenInterfaceMatcherBackend()

    def generate(self, inputs: InterfaceInput, params: InterfaceParams) -> GenerationResult:
        safe_inputs = InterfaceInput(inputs.film.copy(), inputs.substrate.copy())
        lineage = build_binary_lineage(safe_inputs)
        candidates = []
        for film_miller in params.film_millers:
            for substrate_miller in params.substrate_millers:
                matches = self.backend.generate(
                    safe_inputs,
                    film_miller=film_miller,
                    substrate_miller=substrate_miller,
                    film_thickness=float(params.film_thickness),
                    substrate_thickness=float(params.substrate_thickness),
                    vacuum_thickness=float(params.vacuum_thickness),
                    gap=float(params.gap),
                    max_area=float(params.max_area),
                    max_area_ratio_tol=float(params.max_area_ratio_tol),
                    max_length_tol=float(params.max_length_tol),
                    max_angle_tol=float(params.max_angle_tol),
                )
                for match in matches:
                    match.actual_parameters.update(
                        {
                            "film_miller": list(film_miller),
                            "substrate_miller": list(substrate_miller),
                        }
                    )
                    candidates.append(match)
        candidates.sort(
            key=lambda item: (
                float(item.actual_parameters.get("interface_area", float("inf"))),
                float(item.actual_parameters.get("mismatch", float("inf"))),
                structure_sha256(item.structure),
            )
        )
        generated: list[GeneratedStructure] = []
        warnings: list[str] = []
        seen: set[str] = set()
        for match in candidates:
            child = match.structure
            if len(child) > params.max_atoms_per_structure:
                raise ValueError(
                    f"interface atom limit exceeded: {len(child)} > {params.max_atoms_per_structure}"
                )
            child_id = structure_sha256(child)
            if child_id in seen:
                warnings.append("duplicate interface candidate skipped")
                continue
            seen.add(child_id)
            generated.append(
                GeneratedStructure(
                    child,
                    StructureRecord(
                        structure_id=child_id,
                        parent_structure_id=lineage.parent_structure_ids["substrate"],
                        parent_structure_ids=lineage.parent_structure_ids,
                        formula=child.composition.reduced_formula,
                        n_atoms=len(child),
                        actual_parameters=match.actual_parameters,
                        site_mapping=lineage.site_mapping,
                    ),
                )
            )
            if len(generated) >= params.max_structures:
                warnings.append("interface candidates truncated by max_structures")
                break
        if not generated:
            raise ValueError("interface generation produced no matching structures")
        substrate_id = lineage.parent_structure_ids["substrate"]
        return GenerationResult(
            defect_type=self.defect_name,
            input_count=2,
            generated=generated,
            warnings=warnings,
            provenance=Provenance(
                generator=self.defect_name,
                generator_version=self.generator_version,
                input_source="in-memory",
                input_structure_hash=substrate_id,
                input_structure_hashes=lineage.parent_structure_ids,
                parameters=params.model_dump(mode="json"),
                seed=None,
                created_at=datetime.now(timezone.utc),
            ),
        )
