"""Default, non-blocking checks for generated structures."""

from __future__ import annotations

import math

import numpy as np
from pymatgen.core import Structure

from llm_matgen.checks.models import CheckIssue, CheckReport
from llm_matgen.generators.models import CheckLevel
from llm_matgen.utils.structure import assign_site_ids, structure_sha256


class LightStructureChecker:
    def check(
        self,
        structure: Structure,
        reference: Structure | None = None,
        min_distance: float = 0.8,
    ) -> CheckReport:
        issues: list[CheckIssue] = []
        metrics: dict[str, int | float | bool | str | None] = {
            "min_distance_threshold": min_distance,
        }

        if len(structure) == 0:
            issues.append(
                CheckIssue(
                    code="empty-structure",
                    level=CheckLevel.ERROR,
                    message="structure has no sites",
                )
            )

        lattice_matrix = np.asarray(structure.lattice.matrix, dtype=float)
        if not np.isfinite(lattice_matrix).all():
            issues.append(
                CheckIssue(
                    code="non-finite-lattice",
                    level=CheckLevel.ERROR,
                    message="lattice contains non-finite values",
                )
            )
        elif not math.isfinite(float(structure.lattice.volume)) or structure.lattice.volume <= 0:
            issues.append(
                CheckIssue(
                    code="singular-lattice",
                    level=CheckLevel.ERROR,
                    message="lattice volume must be positive and finite",
                )
            )

        frac_coords = np.asarray(structure.frac_coords, dtype=float)
        if not np.isfinite(frac_coords).all():
            issues.append(
                CheckIssue(
                    code="non-finite-coordinates",
                    level=CheckLevel.ERROR,
                    message="fractional coordinates contain non-finite values",
                )
            )

        close_count = 0
        if (
            len(structure) > 0
            and np.isfinite(lattice_matrix).all()
            and math.isfinite(float(structure.lattice.volume))
            and structure.lattice.volume > 0
            and np.isfinite(frac_coords).all()
        ):
            center_indices, neighbor_indices, _, distances = structure.get_neighbor_list(min_distance)
            site_ids = assign_site_ids(structure, structure_sha256(structure))
            for center, neighbor, distance in zip(
                center_indices.tolist(),
                neighbor_indices.tolist(),
                distances.tolist(),
                strict=True,
            ):
                if center == neighbor:
                    continue
                close_count += 1
                issues.append(
                    CheckIssue(
                        code="close-contact",
                        level=CheckLevel.WARNING,
                        message=f"sites are closer than {min_distance} Å",
                        site_ids=[site_ids[center], site_ids[neighbor]],
                        details={"distance": float(distance)},
                    )
                )
        metrics["close_contact_count"] = close_count

        if reference is not None:
            metrics["reference_n_atoms"] = len(reference)
            metrics["composition_changed"] = (
                structure.composition.reduced_formula
                != reference.composition.reduced_formula
            )

        return CheckReport(
            n_atoms=len(structure),
            formula=structure.composition.reduced_formula,
            issues=issues,
            metrics=metrics,
        )
