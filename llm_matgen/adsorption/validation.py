"""Shared fixed-layer policy used by generation and candidate validation."""

from __future__ import annotations

from dataclasses import dataclass
import warnings as _warnings

import numpy as np
from pymatgen.core import Structure


def _surface_normal(structure: Structure) -> np.ndarray:
    normal = np.cross(structure.lattice.matrix[0], structure.lattice.matrix[1]).astype(float)
    normal /= np.linalg.norm(normal)
    if np.dot(normal, structure.lattice.matrix[2]) < 0:
        normal = -normal
    return normal


def _layer_ids(structure: Structure, slab_atom_count: int, tolerance: float = 0.15):
    if not 0 <= slab_atom_count <= len(structure):
        raise ValueError("slab_atom_count must be between zero and the number of atoms")
    if tolerance <= 0 or not np.isfinite(tolerance):
        raise ValueError("tolerance must be finite and positive")
    normal = _surface_normal(structure)
    projections = np.asarray(structure.cart_coords[:slab_atom_count]) @ normal
    order = np.argsort(projections, kind="stable")
    layers: list[list[int]] = []
    for index in order:
        if not layers or abs(float(projections[index]) - float(np.mean(projections[layers[-1]]))) > tolerance:
            layers.append([int(index)])
        else:
            layers[-1].append(int(index))
    return layers, tuple(float(value) for value in projections)


@dataclass(frozen=True)
class FixedLayerResult:
    layer_indices: tuple[tuple[int, ...], ...]
    projections: tuple[float, ...]
    flags: tuple[tuple[bool, bool, bool], ...]
    warnings: tuple[str, ...] = ()


def apply_fixed_bottom_layers(
    structure: Structure,
    *,
    slab_atom_count: int,
    n_layers: int,
    tolerance: float = 0.15,
    side: str = "bottom",
) -> FixedLayerResult:
    if side not in {"bottom", "top", "both"}:
        raise ValueError("side must be bottom, top or both")
    layers, projections = _layer_ids(structure, slab_atom_count, tolerance)
    if n_layers < 0 or n_layers > len(layers):
        raise ValueError(f"n_layers must be between 0 and {len(layers)}")
    existing = structure.site_properties.get("selective_dynamics", [(True, True, True)] * len(structure))
    flags = [tuple(bool(value) for value in row) for row in existing]
    warnings: list[str] = []
    if side in {"top", "both"}:
        warnings.append(f"fixed-layer policy applies bottom layers; requested side={side}")
    selected = {atom for layer in layers[:n_layers] for atom in layer}
    for atom in selected:
        flags[atom] = (False, False, False)
    return FixedLayerResult(tuple(tuple(layer) for layer in layers), projections, tuple(flags), tuple(warnings))

