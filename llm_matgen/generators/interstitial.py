"""Interstitial structure generation with bounded candidate search."""

from __future__ import annotations

from itertools import combinations
from datetime import datetime, timezone

import numpy as np
from pydantic import Field, PositiveFloat, PositiveInt
from pymatgen.core import Structure
from scipy.spatial import Voronoi

from llm_matgen.generators.base import Supercell, apply_supercell
from llm_matgen.generators.models import (
    GeneratedStructure,
    GenerationResult,
    Provenance,
    RandomGenerationParams,
    StructureRecord,
)
from llm_matgen.utils.structure import assign_site_ids, structure_sha256


class InterstitialParams(RandomGenerationParams):
    elements: list[str] = Field(min_length=1)
    counts: list[PositiveInt]
    variants_per_count: PositiveInt = 1
    min_distance: PositiveFloat = 0.8
    max_attempts: PositiveInt = 1000
    candidate_mode: str = "voronoi"
    supercell: Supercell | None = None


def _minimum_distance(structure: Structure, frac_coords: np.ndarray) -> float:
    cart_coords = structure.lattice.get_cartesian_coords(frac_coords)
    return min(
        structure.lattice.get_distance_and_image(site.coords, cart_coords)[0]
        for site in structure
    )


def find_voronoi_candidates(
    structure: Structure,
    *,
    min_distance: float,
) -> list[np.ndarray]:
    offsets = np.array(
        [(i, j, k) for i in (-1, 0, 1) for j in (-1, 0, 1) for k in (-1, 0, 1)],
        dtype=float,
    )
    replicated = np.concatenate(
        [
            structure.cart_coords + structure.lattice.get_cartesian_coords(offset)
            for offset in offsets
        ]
    )
    candidates: list[np.ndarray] = []
    try:
        vertices = Voronoi(replicated).vertices
    except Exception:
        vertices = np.empty((0, 3))
    for vertex in vertices:
        frac = np.mod(structure.lattice.get_fractional_coords(vertex), 1.0)
        if _minimum_distance(structure, frac) < min_distance:
            continue
        if not any(np.allclose(frac, existing, atol=1e-8) for existing in candidates):
            candidates.append(frac)
    if not candidates:
        for x in np.linspace(0.0, 0.875, 8):
            for y in np.linspace(0.0, 0.875, 8):
                for z in np.linspace(0.0, 0.875, 8):
                    frac = np.array([x, y, z])
                    if _minimum_distance(structure, frac) >= min_distance:
                        candidates.append(frac)
        candidates = sorted(candidates, key=lambda item: tuple(np.round(item, 10)))
    return sorted(candidates, key=lambda item: tuple(np.round(item, 10)))


def _find_random_candidates(
    structure: Structure,
    *,
    min_distance: float,
    max_attempts: int,
    rng: np.random.Generator,
) -> list[np.ndarray]:
    candidates: list[np.ndarray] = []
    for _ in range(max_attempts):
        candidate = rng.random(3)
        if _minimum_distance(structure, candidate) < min_distance:
            continue
        if all(
            structure.lattice.get_distance_and_image(
                structure.lattice.get_cartesian_coords(existing),
                structure.lattice.get_cartesian_coords(candidate),
            )[0]
            >= min_distance
            for existing in candidates
        ):
            candidates.append(candidate)
    return candidates


class InterstitialGenerator:
    defect_name = "interstitial"
    generator_version = "0.1.0"

    def generate(self, structure: Structure, params: InterstitialParams) -> GenerationResult:
        source = apply_supercell(structure, params.supercell) if params.supercell else structure.copy()
        parent_id = structure_sha256(source)
        parent_site_ids = assign_site_ids(source, parent_id)
        resolved_seed = params.seed
        if resolved_seed is None:
            resolved_seed = int(np.random.SeedSequence().entropy)
        rng = np.random.default_rng(resolved_seed)
        if params.candidate_mode == "voronoi":
            candidates = find_voronoi_candidates(source, min_distance=params.min_distance)
        elif params.candidate_mode == "random":
            candidates = _find_random_candidates(
                source,
                min_distance=params.min_distance,
                max_attempts=params.max_attempts,
                rng=rng,
            )
        else:
            raise ValueError(f"unsupported interstitial candidate mode: {params.candidate_mode}")

        generated: list[GeneratedStructure] = []
        warnings: list[str] = []
        for element in params.elements:
            for count in params.counts:
                if count > len(candidates):
                    warnings.append(
                        f"not enough interstitial candidates for {element} count {count}"
                    )
                    continue
                combinations_available = list(combinations(range(len(candidates)), count))
                selected = combinations_available[: params.variants_per_count]
                if len(combinations_available) > params.variants_per_count:
                    selected_indices = rng.choice(
                        len(combinations_available),
                        size=params.variants_per_count,
                        replace=False,
                    )
                    selected = [
                        combinations_available[index] for index in sorted(selected_indices)
                    ]
                for candidate_indices in selected:
                    child = source.copy()
                    selected_positions = [candidates[index] for index in candidate_indices]
                    for position in selected_positions:
                        child.append(element, position, coords_are_cartesian=False)
                    child_id = structure_sha256(child)
                    child_site_ids = assign_site_ids(child, child_id)
                    mapping = {
                        parent_site_ids[index]: child_site_ids[index]
                        for index in range(len(source))
                    }
                    for index in range(count):
                        mapping[f"new-site-{index}"] = None
                    generated.append(
                        GeneratedStructure(
                            structure=child,
                            record=StructureRecord(
                                structure_id=child_id,
                                parent_structure_id=parent_id,
                                formula=child.composition.reduced_formula,
                                n_atoms=len(child),
                                actual_parameters={
                                    "element": element,
                                    "count": count,
                                    "fractional_positions": [
                                        position.tolist() for position in selected_positions
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
            if len(generated) >= params.max_structures:
                break
        if len(generated) >= params.max_structures:
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
