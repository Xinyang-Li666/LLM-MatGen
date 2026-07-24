"""Deterministic crystal-structure classification from geometry and coordination."""

from __future__ import annotations

from typing import Any, Protocol

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from pymatgen.core import Structure

from llm_matgen.generators.models import JsonValue


class ClassificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    matched: bool
    score: float = Field(ge=0, le=1)
    method: str
    evidence: dict[str, JsonValue]


class StructureClassifier(Protocol):
    def classify(self, structure: Structure, target: str | None = None) -> ClassificationResult: ...


class DeterministicStructureClassifier:
    method = "geometry-and-coordination"

    def classify(self, structure: Structure, target: str | None = None) -> ClassificationResult:
        try:
            evidence = self._evidence(structure)
            label = self._label(evidence)
        except Exception as exc:
            evidence = {"error": type(exc).__name__}
            label = "unknown"
        return ClassificationResult(
            label=label,
            matched=(label == target) if target is not None else label != "unknown",
            score=1.0 if label != "unknown" else 0.0,
            method=self.method,
            evidence=evidence,
        )

    def _evidence(self, structure: Structure) -> dict[str, JsonValue]:
        if len(structure) == 0:
            raise ValueError("empty structure")
        reduced = structure.composition.reduced_composition
        amounts = {element.symbol: float(amount) for element, amount in reduced.items()}
        coordination = self._coordination_by_element(structure)
        rank, nearest_distance, bond_count = self._connectivity_rank(structure)
        electronegativities = {
            element.symbol: float(element.X) if element.X is not None else -1.0
            for element in reduced.elements
        }
        anion = max(electronegativities, key=electronegativities.get)
        return {
            "reduced_amounts": amounts,
            "coordination": coordination,
            "connectivity_rank": rank,
            "nearest_distance": nearest_distance,
            "nearest_bond_count": bond_count,
            "anion_candidate": anion,
        }

    @staticmethod
    def _coordination_by_element(structure: Structure) -> dict[str, float]:
        values: dict[str, list[int]] = {}
        search_radius = max(structure.lattice.abc)
        for site in structure:
            neighbors = structure.get_neighbors(site, search_radius)
            positive = [neighbor for neighbor in neighbors if neighbor.nn_distance > 1e-8]
            if not positive:
                coordination = 0
            else:
                nearest = min(neighbor.nn_distance for neighbor in positive)
                coordination = sum(
                    neighbor.nn_distance <= nearest * 1.15 + 1e-8 for neighbor in positive
                )
            values.setdefault(site.specie.symbol, []).append(int(coordination))
        return {
            element: float(np.mean(counts))
            for element, counts in sorted(values.items())
        }

    @staticmethod
    def _connectivity_rank(structure: Structure) -> tuple[int, float, int]:
        radius = max(structure.lattice.abc)
        _, _, _, distances = structure.get_neighbor_list(radius)
        positive = distances[distances > 1e-8]
        if positive.size == 0:
            return 0, 0.0, 0
        nearest = float(positive.min())
        _, _, offsets, shell_distances = structure.get_neighbor_list(nearest * 1.15 + 1e-8)
        shell_offsets = np.asarray(offsets)[shell_distances > 1e-8]
        rank = int(np.linalg.matrix_rank(shell_offsets)) if len(shell_offsets) else 0
        return rank, nearest, int(len(shell_offsets))

    @staticmethod
    def _near(value: float, expected: float, tolerance: float = 0.6) -> bool:
        return abs(value - expected) <= tolerance

    def _label(self, evidence: dict[str, Any]) -> str:
        amounts: dict[str, float] = evidence["reduced_amounts"]
        coordination: dict[str, float] = evidence["coordination"]
        anion = evidence["anion_candidate"]
        if (
            evidence["connectivity_rank"] <= 2
            and evidence["nearest_bond_count"] > 0
            and max(coordination.values()) <= 4.5
        ):
            return "layered"

        sorted_amounts = sorted(amounts.values())
        if len(amounts) == 2 and np.allclose(sorted_amounts, [1, 1]):
            if all(self._near(value, 6) for value in coordination.values()):
                return "rocksalt"
        if len(amounts) == 2 and np.allclose(sorted_amounts, [1, 2]):
            other = next(element for element in amounts if element != anion)
            if (
                amounts[anion] == 2
                and self._near(coordination.get(other, 0), 8)
                and self._near(coordination.get(anion, 0), 4)
            ):
                return "fluorite"
        if len(amounts) == 3 and np.allclose(sorted_amounts, [1, 1, 3]):
            cation_coords = [value for element, value in coordination.items() if element != anion]
            if (
                amounts[anion] == 3
                and any(self._near(value, 6) for value in cation_coords)
                and any(value >= 8 for value in cation_coords)
            ):
                return "perovskite"
        if len(amounts) == 3 and np.allclose(sorted_amounts, [1, 2, 4]):
            cation_coords = sorted(
                value for element, value in coordination.items() if element != anion
            )
            if amounts[anion] == 4 and any(self._near(value, 4) for value in cation_coords) and any(
                self._near(value, 6) for value in cation_coords
            ):
                return "spinel"
        return "unknown"
