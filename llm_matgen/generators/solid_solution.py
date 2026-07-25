"""Random solid-solution generation with explicit realized ratios."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
from pydantic import Field, PositiveInt, model_validator
from pymatgen.core import Structure

from llm_matgen.generators.base import Supercell, apply_supercell
from llm_matgen.generators.backends import (
    BackendGenerationError,
    OptionalDependencyError,
    SQSBackend,
)
from llm_matgen.generators.models import (
    GeneratedStructure,
    GenerationResult,
    Provenance,
    RandomGenerationParams,
    StructureRecord,
)
from llm_matgen.utils.structure import assign_site_ids, structure_sha256


class SolidSolutionParams(RandomGenerationParams):
    target_element: str
    substituents: dict[str, float] = Field(min_length=1)
    method: str = "random"
    variants: PositiveInt = 1
    sqs_iterations: PositiveInt = 50_000
    supercell: Supercell | tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]] | None = None

    @model_validator(mode="after")
    def validate_ratios(self):
        if self.method not in {"random", "sqs"}:
            raise ValueError(f"unsupported solid solution method: {self.method!r}")
        if any(value <= 0 for value in self.substituents.values()):
            raise ValueError("substituent ratios must be positive")
        if not np.isclose(sum(self.substituents.values()), 1.0):
            raise ValueError("substituent ratios must sum to 1")
        if self.target_element in self.substituents:
            raise ValueError("target element cannot also be a substituent")
        return self


def _normalize_supercell(value):
    if value is None or isinstance(value, Supercell):
        return value
    return Supercell(matrix=value)


class SolidSolutionGenerator:
    defect_name = "solid_solution"
    generator_version = "0.1.0"

    def generate(self, structure: Structure, params: SolidSolutionParams) -> GenerationResult:
        source = (
            apply_supercell(structure, _normalize_supercell(params.supercell))
            if params.supercell
            else structure.copy()
        )
        if params.method == "sqs":
            try:
                return SQSBackend().generate(
                    source,
                    params.target_element,
                    params.substituents,
                    params.seed,
                    iterations=params.sqs_iterations,
                    variants=params.variants,
                    max_structures=params.max_structures,
                    max_atoms=params.max_atoms_per_structure,
                )
            except (OptionalDependencyError, BackendGenerationError) as exc:
                raise type(exc)(f"{exc}; use --method random to continue") from exc
        parent_id = structure_sha256(source)
        parent_site_ids = assign_site_ids(source, parent_id)
        target_indices = [
            index for index, site in enumerate(source) if site.specie.symbol == params.target_element
        ]
        if not target_indices:
            raise ValueError("target element is not present in the input structure")
        resolved_seed = params.seed
        if resolved_seed is None:
            resolved_seed = int(np.random.SeedSequence().entropy)
        rng = np.random.default_rng(resolved_seed)

        raw_counts = {
            element: ratio * len(target_indices)
            for element, ratio in params.substituents.items()
        }
        counts = {element: int(np.floor(value)) for element, value in raw_counts.items()}
        remainder = len(target_indices) - sum(counts.values())
        order = sorted(
            raw_counts,
            key=lambda element: (raw_counts[element] - counts[element], element),
            reverse=True,
        )
        for element in order[:remainder]:
            counts[element] += 1
        assignments = [element for element, count in counts.items() for _ in range(count)]
        generated: list[GeneratedStructure] = []
        for _ in range(params.variants):
            assignment = list(assignments)
            rng.shuffle(assignment)
            child = source.copy()
            for site_index, element in zip(target_indices, assignment, strict=True):
                child.replace(site_index, element)
            child_id = structure_sha256(child)
            child_site_ids = assign_site_ids(child, child_id)
            generated.append(
                GeneratedStructure(
                    structure=child,
                    record=StructureRecord(
                        structure_id=child_id,
                        parent_structure_id=parent_id,
                        formula=child.composition.reduced_formula,
                        n_atoms=len(child),
                        actual_parameters={
                            "requested_ratios": params.substituents,
                            "actual_ratios": {
                                element: counts[element] / len(target_indices)
                                for element in params.substituents
                            },
                            "counts": counts,
                        },
                        site_mapping={
                            parent_site_ids[index]: child_site_ids[index]
                            for index in range(len(source))
                        },
                    ),
                )
            )
            if len(generated) >= params.max_structures:
                break
        return GenerationResult(
            defect_type=self.defect_name,
            input_count=1,
            skipped_count=0,
            generated=generated,
            provenance=Provenance(
                generator=self.defect_name,
                generator_version=self.generator_version,
                input_source="in-memory",
                input_structure_hash=parent_id,
                parameters=params.model_dump(mode="json"),
                seed=resolved_seed,
                created_at=datetime.now(timezone.utc),
            ),
        )
