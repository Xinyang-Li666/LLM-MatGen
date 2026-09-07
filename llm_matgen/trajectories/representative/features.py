"""Hybrid RDF, local-neighbour and cell feature pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
import warnings

import numpy as np
from ase import Atoms
from ase.neighborlist import neighbor_list

from llm_matgen.trajectories.filtering.models import FilterFrame
from .rdf import RDFDescriptor


@dataclass(frozen=True)
class FeatureSchema:
    names: tuple[str, ...]
    blocks: tuple[str, ...]
    active: tuple[bool, ...]


def infer_coordination_cutoff(distances: np.ndarray, explicit: float | None = None) -> tuple[float, str | None]:
    if explicit is not None:
        if not np.isfinite(explicit) or explicit <= 0:
            raise ValueError("coordination cutoff must be positive")
        return float(explicit), None
    values = np.asarray(distances, dtype=float)
    values = values[np.isfinite(values) & (values > 0)]
    if values.size >= 4:
        hist, edges = np.histogram(values, bins=min(32, max(4, int(np.sqrt(values.size)))))
        for index in range(1, len(hist) - 1):
            if hist[index] <= hist[index - 1] and hist[index] <= hist[index + 1]:
                return float(edges[index + 1]), None
    fallback = float(np.median(values) * 1.25) if values.size else 3.0
    return fallback, "coordination cutoff fell back to robust distance estimate"


class RDFFeaturePipeline:
    def __init__(self, rdf: RDFDescriptor, coordination_cutoff: float | None = None, weights=(0.65, 0.25, 0.10)):
        if len(weights) != 3 or any(float(weight) < 0 for weight in weights) or not np.isclose(sum(weights), 1.0):
            raise ValueError("weights must be three non-negative values summing to one")
        self.rdf = rdf
        self.coordination_cutoff = coordination_cutoff
        self.weights = tuple(float(weight) for weight in weights)
        self.schema: FeatureSchema | None = None
        self._median: np.ndarray | None = None
        self._scale: np.ndarray | None = None

    def fit(self, frames: Iterable[FilterFrame]) -> FeatureSchema:
        rows = [self._raw(frame) for frame in frames]
        if not rows:
            raise ValueError("at least one frame is required")
        matrix = np.vstack(rows)
        median = np.median(matrix, axis=0)
        q25, q75 = np.quantile(matrix, [0.25, 0.75], axis=0)
        scale = q75 - q25
        fallback = np.std(matrix, axis=0)
        scale = np.where((scale <= 0) & (fallback > 0), fallback, scale)
        active = scale > 0
        scale = np.where(active, scale, 1.0)
        self._median, self._scale = median, scale
        names = tuple(self.rdf.feature_names) + tuple(
            f"coord:{name}" for name in ("mean", "std", "q25", "median", "q75")
        ) + tuple(f"cell:{name}" for name in ("volume", "number_density", "per_atom_volume", "a", "b", "c", "alpha", "beta", "gamma"))
        blocks = tuple("rdf" for _ in self.rdf.feature_names) + tuple("coord" for _ in range(5)) + tuple("cell" for _ in range(9))
        self.schema = FeatureSchema(names, blocks, tuple(bool(value) for value in active))
        return self.schema

    def transform(self, frame: FilterFrame) -> np.ndarray:
        if self.schema is None or self._median is None or self._scale is None:
            raise RuntimeError("pipeline must be fitted before transform")
        raw = self._raw(frame)
        values = (raw - self._median) / self._scale
        values[~np.asarray(self.schema.active, dtype=bool)] = 0.0
        for block, weight in zip(("rdf", "coord", "cell"), self.weights):
            indices = np.flatnonzero(np.array(self.schema.blocks) == block)
            if indices.size:
                values[indices] *= weight / np.sqrt(indices.size)
        return values.astype(np.float32)

    def _raw(self, frame: FilterFrame) -> np.ndarray:
        rdf_values = self.rdf.describe(frame)
        atoms = Atoms(numbers=frame.atomic_numbers, positions=frame.positions, cell=frame.cell, pbc=frame.pbc)
        centers, _, distances = neighbor_list("ijd", atoms, self.coordination_cutoff or self.rdf.r_max)
        cutoff, warning = infer_coordination_cutoff(distances, self.coordination_cutoff)
        if warning:
            warnings.warn(warning, RuntimeWarning, stacklevel=2)
        counts = np.bincount(centers[distances < cutoff], minlength=frame.natoms)
        coord = np.quantile(counts, [0.5, 0.5, 0.25, 0.5, 0.75]).astype(float)
        coord[0] = float(np.mean(counts)); coord[1] = float(np.std(counts))
        if frame.cell is None:
            cell = np.zeros(9, dtype=float)
        else:
            vectors = np.asarray(frame.cell, dtype=float)
            lengths = np.linalg.norm(vectors, axis=1)
            angles = [np.degrees(np.arccos(np.clip(np.dot(vectors[i], vectors[(i + 1) % 3]) / (lengths[i] * lengths[(i + 1) % 3]), -1, 1))) for i in range(3)]
            volume = abs(float(np.linalg.det(vectors)))
            cell = np.array([volume, frame.natoms / volume if volume else 0, volume / frame.natoms, *lengths, *angles])
        return np.concatenate((rdf_values, coord, cell))
