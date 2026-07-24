"""Substitutional vacancy generation."""

from __future__ import annotations

from itertools import combinations
from datetime import datetime, timezone

import numpy as np
from pydantic import Field, PositiveInt
from pymatgen.core import Structure

from llm_matgen.generators.base import Supercell, apply_supercell
from llm_matgen.generators.models import (
    GeneratedStructure,
    GenerationResult,
    Provenance,
    RandomGenerationParams,
    StructureRecord,
)
from llm_matgen.utils.structure import assign_site_ids, structure_sha256


class VacancyParams(RandomGenerationParams):
    target_elements: list[str] = Field(min_length=1)
    concentration: float | None = Field(default=None, gt=0, lt=1)
    counts: list[PositiveInt] | None = None
    variants_per_count: PositiveInt = 1
    supercell: Supercell | None = None


class VacancyGenerator:
    defect_name = "vacancy"
    generator_version = "0.1.0"

    def generate(self, structure: Structure, params: VacancyParams) -> GenerationResult:
        source = apply_supercell(structure, params.supercell) if params.supercell else structure.copy()
        parent_id = structure_sha256(source)
        parent_site_ids = assign_site_ids(source, parent_id)
        target_set = set(params.target_elements)
        target_indices = [
            index for index, site in enumerate(source) if site.specie.symbol in target_set
        ]
        if not target_indices:
            raise ValueError("target elements are not present in the input structure")

        counts = list(params.counts or [])
        if not counts:
            assert params.concentration is not None
            counts = [max(1, round(len(target_indices) * params.concentration))]
        if any(count > len(target_indices) for count in counts):
            raise ValueError("vacancy count exceeds available target sites")
        resolved_seed = params.seed
        if resolved_seed is None:
            resolved_seed = int(np.random.SeedSequence().entropy)
        rng = np.random.default_rng(resolved_seed)

        generated: list[GeneratedStructure] = []
        for count in counts:
            candidates = list(combinations(target_indices, count))
            if len(candidates) > params.variants_per_count:
                selected_indices = rng.choice(
                    len(candidates),
                    size=params.variants_per_count,
                    replace=False,
                )
                selected = [candidates[index] for index in sorted(selected_indices)]
            else:
                selected = candidates
            for removed in selected:
                child = source.copy()
                child.remove_sites(list(removed))
                if len(child) == 0:
                    raise ValueError("vacancy generation cannot remove all atoms")
                child_id = structure_sha256(child)
                child_site_ids = assign_site_ids(child, child_id)
                child_position = 0
                mapping: dict[str, str | None] = {}
                removed_set = set(removed)
                for original_index, parent_site_id in enumerate(parent_site_ids):
                    if original_index in removed_set:
                        mapping[parent_site_id] = None
                    else:
                        mapping[parent_site_id] = child_site_ids[child_position]
                        child_position += 1
                generated.append(
                    GeneratedStructure(
                        structure=child,
                        record=StructureRecord(
                            structure_id=child_id,
                            parent_structure_id=parent_id,
                            formula=child.composition.reduced_formula,
                            n_atoms=len(child),
                            actual_parameters={
                                "requested_count": count,
                                "actual_count": count,
                                "actual_concentration": count / len(target_indices),
                                "removed_site_ids": [
                                    parent_site_ids[index] for index in removed
                                ],
                            },
                            site_mapping=mapping,
                        ),
                    )
                )
                if len(generated) >= params.max_structures:
                    break
            if len(generated) >= params.max_structures:
                break

        warnings = []
        total_candidates = sum(
            min(len(list(combinations(target_indices, count))), params.variants_per_count)
            for count in counts
        )
        if total_candidates > len(generated):
            warnings.append("generation truncated by max_structures")
        return GenerationResult(
            defect_type=self.defect_name,
            input_count=1,
            skipped_count=0,
            generated=generated,
            warnings=warnings,
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
