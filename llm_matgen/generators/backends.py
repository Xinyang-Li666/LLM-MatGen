"""Optional generator backend contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

import numpy as np
from pymatgen.core import Structure
from pymatgen.core import Lattice
from pymatgen.core.interface import GrainBoundaryGenerator as PymatgenGBBuilder
from pymatgen.analysis.interfaces.coherent_interfaces import CoherentInterfaceBuilder
from pymatgen.analysis.interfaces.zsl import ZSLGenerator


class OptionalDependencyError(ImportError):
    """Raised when an explicitly requested optional backend is unavailable."""


class BackendGenerationError(RuntimeError):
    """Raised when a local crystallographic backend cannot construct a result."""


@dataclass
class BackendStructure:
    structure: Structure
    actual_parameters: dict[str, object]


class GrainBoundaryBackend(Protocol):
    def generate(
        self,
        structure: Structure,
        *,
        rotation_axis: tuple[int, int, int],
        rotation_angle: float,
        plane: tuple[int, int, int] | None,
        expand_times: int,
        vacuum_thickness: float,
        ab_shift: tuple[float, float],
    ) -> BackendStructure: ...


class PymatgenGrainBoundaryBackend:
    def generate(
        self,
        structure: Structure,
        *,
        rotation_axis: tuple[int, int, int],
        rotation_angle: float,
        plane: tuple[int, int, int] | None,
        expand_times: int,
        vacuum_thickness: float,
        ab_shift: tuple[float, float],
    ) -> BackendStructure:
        try:
            boundary = PymatgenGBBuilder(structure.copy()).gb_from_parameters(
                rotation_axis=rotation_axis,
                rotation_angle=rotation_angle,
                plane=plane,
                expand_times=expand_times,
                vacuum_thickness=vacuum_thickness,
                ab_shift=ab_shift,
            )
        except Exception as exc:
            raise BackendGenerationError(f"grain-boundary backend failed: {exc}") from exc
        if boundary is None or len(boundary) == 0:
            raise BackendGenerationError("grain-boundary backend returned no structure")
        return BackendStructure(
            structure=boundary,
            actual_parameters={
                "rotation_axis": list(rotation_axis),
                "rotation_angle": rotation_angle,
                "plane": list(plane) if plane else None,
                "expand_times": expand_times,
                "vacuum_thickness": vacuum_thickness,
                "ab_shift": list(ab_shift),
            },
        )


class InterfaceMatcherBackend(Protocol):
    def generate(self, inputs, **kwargs) -> list[BackendStructure]: ...


class PymatgenInterfaceMatcherBackend:
    """Version-isolated adapter around pymatgen ZSL/coherent interfaces."""

    def generate(self, inputs, **kwargs) -> list[BackendStructure]:
        film_miller = kwargs["film_miller"]
        substrate_miller = kwargs["substrate_miller"]
        zsl = ZSLGenerator(
            max_area_ratio_tol=kwargs["max_area_ratio_tol"],
            max_area=kwargs["max_area"],
            max_length_tol=kwargs["max_length_tol"],
            max_angle_tol=kwargs["max_angle_tol"],
        )
        try:
            builder = CoherentInterfaceBuilder(
                substrate_structure=inputs.substrate.copy(),
                film_structure=inputs.film.copy(),
                film_miller=film_miller,
                substrate_miller=substrate_miller,
                zslgen=zsl,
            )
            results: list[BackendStructure] = []
            for termination in builder.terminations:
                for interface in builder.get_interfaces(
                    termination=termination,
                    gap=kwargs["gap"],
                    vacuum_over_film=kwargs["vacuum_thickness"],
                    film_thickness=kwargs["film_thickness"],
                    substrate_thickness=kwargs["substrate_thickness"],
                    in_layers=False,
                ):
                    area = float(np.linalg.norm(np.cross(interface.lattice.matrix[0], interface.lattice.matrix[1])))
                    results.append(
                        BackendStructure(
                            interface,
                            {
                                "interface_area": area,
                                "mismatch": 0.0,
                                "termination": [str(item) for item in termination],
                            },
                        )
                    )
            return results
        except Exception as exc:
            raise BackendGenerationError(f"interface backend failed: {exc}") from exc


class SQSBackend:
    @staticmethod
    def _replacement_counts(structure, target_element, substituents):
        target_count = sum(site.specie.symbol == target_element for site in structure)
        if target_count == 0:
            raise ValueError(f"target element is not present in the input structure: {target_element}")
        raw = {element: ratio * target_count for element, ratio in substituents.items()}
        counts = {element: int(np.floor(value)) for element, value in raw.items()}
        remainder = target_count - sum(counts.values())
        order = sorted(
            raw,
            key=lambda element: (raw[element] - counts[element], element),
            reverse=True,
        )
        for element in order[:remainder]:
            counts[element] += 1
        return counts

    @classmethod
    def build_config(cls, structure, target_element, substituents, iterations, seed):
        counts = cls._replacement_counts(structure, target_element, substituents)
        target_count = sum(site.specie.symbol == target_element for site in structure)
        composition = []
        seen = set()
        for site in structure:
            element = site.specie.symbol
            if element in seen:
                continue
            seen.add(element)
            if element == target_element:
                entry = {"sites": element, element: target_count - sum(counts.values())}
                entry.update(counts)
            else:
                entry = {"sites": element, element: sum(s.specie.symbol == element for s in structure)}
            composition.append(entry)
        return {
            "structure": {
                "lattice": structure.lattice.matrix.tolist(),
                "coords": structure.frac_coords.tolist(),
                "species": [site.specie.symbol for site in structure],
            },
            "composition": composition,
            "iterations": iterations,
            "sublattice_mode": "split",
            "iteration_mode": "random",
            "thread_config": [1],
            "seed": seed,
        }

    @staticmethod
    def _to_pymatgen(result):
        return Structure(
            Lattice(result.lattice),
            list(result.symbols),
            result.frac_coords,
            coords_are_cartesian=False,
        )

    def generate(
        self,
        structure,
        target_element,
        substituents,
        seed,
        *,
        iterations=50_000,
        variants=1,
        max_structures=1000,
        max_atoms=100_000,
    ):
        from llm_matgen.generators.models import (
            GeneratedStructure,
            GenerationResult,
            Provenance,
            StructureRecord,
        )
        from llm_matgen.utils.structure import assign_site_ids, structure_sha256

        try:
            import sqsgenerator
            import sqsgenerator.core._core as sqs_core
        except ImportError as exc:
            raise OptionalDependencyError(
                "SQS generation requires the optional dependency sqsgenerator; "
                "install with pip install llm-matgen[sqs], or use --method random"
            ) from exc

        parent_id = structure_sha256(structure)
        parent_site_ids = assign_site_ids(structure, parent_id)
        resolved_seed = seed if seed is not None else int(np.random.SeedSequence().entropy)
        generated = []
        seed_sequence = np.random.SeedSequence(resolved_seed)
        child_seeds = seed_sequence.spawn(min(variants, max_structures))
        try:
            for child_seed in child_seeds:
                config = self.build_config(
                    structure,
                    target_element,
                    substituents,
                    iterations,
                    int(child_seed.generate_state(1)[0]),
                )
                parsed = sqsgenerator.parse_config(config)
                if isinstance(parsed, sqs_core.ParseError):
                    raise ValueError(f"sqsgenerator configuration error: {parsed.msg}")
                optimized = sqsgenerator.optimize(parsed)
                best = optimized.best()
                sqs_structure = best.structure() if callable(best.structure) else best.structure
                child = self._to_pymatgen(sqs_structure)
                if len(child) > max_atoms:
                    raise ValueError(f"SQS structure exceeds max_atoms={max_atoms}")
                child_id = structure_sha256(child)
                child_site_ids = assign_site_ids(child, child_id)
                mapping = {
                    parent_site_ids[index]: child_site_ids[index] if index < len(child_site_ids) else None
                    for index in range(len(parent_site_ids))
                }
                for index in range(len(parent_site_ids), len(child_site_ids)):
                    mapping[f"new-site-{index}"] = child_site_ids[index]
                generated.append(
                    GeneratedStructure(
                        structure=child,
                        record=StructureRecord(
                            structure_id=child_id,
                            parent_structure_id=parent_id,
                            formula=child.composition.reduced_formula,
                            n_atoms=len(child),
                            actual_parameters={
                                "method": "sqs",
                                "iterations": iterations,
                                "requested_ratios": substituents,
                                "seed": config["seed"],
                            },
                            site_mapping=mapping,
                        ),
                    )
                )
        except Exception as exc:
            raise BackendGenerationError(
                f"SQS generation failed: {exc}; use --method random to continue"
            ) from exc
        return GenerationResult(
            defect_type="solid_solution",
            input_count=1,
            generated=generated,
            provenance=Provenance(
                generator="solid_solution",
                generator_version="0.1.0",
                input_source="in-memory",
                input_structure_hash=parent_id,
                parameters={
                    "target_element": target_element,
                    "substituents": substituents,
                    "method": "sqs",
                    "sqs_iterations": iterations,
                    "variants": variants,
                },
                seed=resolved_seed,
                created_at=datetime.now(timezone.utc),
            ),
        )
