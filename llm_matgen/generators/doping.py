"""Substitutional doping generation."""

from __future__ import annotations

from datetime import datetime, timezone
from itertools import combinations, permutations, product

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


class DopingParams(RandomGenerationParams):
    dopant_elements: list[str] = Field(min_length=1)
    target_elements: list[str] = Field(min_length=1)
    dopant_counts: list[PositiveInt]
    variants_per_combination: PositiveInt = 1
    allow_repeated_dopant: bool = False
    supercell: Supercell | None = None


class DopingGenerator:
    defect_name = "doping"
    generator_version = "0.1.0"

    def generate(self, structure: Structure, params: DopingParams) -> GenerationResult:
        source = apply_supercell(structure, params.supercell) if params.supercell else structure.copy()
        parent_id = structure_sha256(source)
        parent_site_ids = assign_site_ids(source, parent_id)
        target_set = set(params.target_elements)
        if target_set.intersection(params.dopant_elements):
            raise ValueError("dopant elements must differ from target elements")
        target_indices = [
            index for index, site in enumerate(source) if site.specie.symbol in target_set
        ]
        if not target_indices:
            raise ValueError("target elements are not present in the input structure")
        resolved_seed = params.seed
        if resolved_seed is None:
            resolved_seed = int(np.random.SeedSequence().entropy)
        rng = np.random.default_rng(resolved_seed)

        generated: list[GeneratedStructure] = []
        for count in params.dopant_counts:
            if count > len(target_indices):
                raise ValueError("dopant count exceeds available target sites")
            site_combinations = list(combinations(target_indices, count))
            if params.allow_repeated_dopant:
                assignments = list(product(params.dopant_elements, repeat=count))
            else:
                assignments = list(permutations(params.dopant_elements, count))
            if not assignments:
                raise ValueError("not enough distinct dopant elements for requested count")
            choices = [(sites, assignment) for sites in site_combinations for assignment in assignments]
            if len(choices) > params.variants_per_combination:
                selected_indices = rng.choice(
                    len(choices),
                    size=params.variants_per_combination,
                    replace=False,
                )
                choices = [choices[index] for index in sorted(selected_indices)]
            for sites, assignment in choices:
                child = source.copy()
                for site_index, element in zip(sites, assignment, strict=True):
                    child.replace(site_index, element)
                child_id = structure_sha256(child)
                child_site_ids = assign_site_ids(child, child_id)
                mapping = {
                    parent_site_ids[index]: child_site_ids[index]
                    for index in range(len(source))
                }
                generated.append(
                    GeneratedStructure(
                        structure=child,
                        record=StructureRecord(
                            structure_id=child_id,
                            parent_structure_id=parent_id,
                            formula=child.composition.reduced_formula,
                            n_atoms=len(child),
                            actual_parameters={
                                "dopant_elements": list(assignment),
                                "target_site_ids": [
                                    parent_site_ids[index] for index in sites
                                ],
                                "count": count,
                            },
                            site_mapping=mapping,
                        ),
                    )
                )
                if len(generated) >= params.max_structures:
                    break
            if len(generated) >= params.max_structures:
                break

        warnings = ["generation truncated by max_structures"] if len(generated) >= params.max_structures else []
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
