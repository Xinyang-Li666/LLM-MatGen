"""Isotropic dislocation displacement fields and structure construction."""

from __future__ import annotations

import numpy as np


def isotropic_displacement_field(
    points: np.ndarray,
    burgers_vector: tuple[float, float, float],
    character: str,
    poisson_ratio: float,
    core_cutoff: float = 1e-6,
) -> np.ndarray:
    """Return Cartesian displacements for a straight line along the z axis."""
    coordinates = np.asarray(points, dtype=float)
    burgers = np.asarray(burgers_vector, dtype=float)
    if coordinates.ndim != 2 or coordinates.shape[1] != 3:
        raise ValueError("points must have shape (n, 3)")
    if not np.isfinite(burgers).all() or np.allclose(burgers, 0):
        raise ValueError("Burgers vector must be finite and non-zero")
    if not -1 < poisson_ratio < 0.5:
        raise ValueError("Poisson ratio must lie between -1 and 0.5")
    if character not in {"edge", "screw", "mixed"}:
        raise ValueError("character must be edge, screw, or mixed")
    if core_cutoff <= 0:
        raise ValueError("core cutoff must be positive")

    x = coordinates[:, 0]
    y = coordinates[:, 1]
    radius_sq = np.maximum(x * x + y * y, core_cutoff * core_cutoff)
    theta = np.arctan2(y, x)
    displacement = np.zeros_like(coordinates, dtype=float)

    if character in {"edge", "mixed"}:
        edge_magnitude = float(np.linalg.norm(burgers[:2]))
        if character == "edge" and edge_magnitude == 0:
            raise ValueError("edge Burgers vector must have an in-plane component")
        if edge_magnitude:
            ux = edge_magnitude / (2 * np.pi) * (
                theta + x * y / (2 * (1 - poisson_ratio) * radius_sq)
            )
            uy = -edge_magnitude / (2 * np.pi) * (
                (1 - 2 * poisson_ratio)
                / (4 * (1 - poisson_ratio))
                * np.log(radius_sq)
                + (x * x - y * y) / (4 * (1 - poisson_ratio) * radius_sq)
            )
            direction = burgers[:2] / edge_magnitude
            displacement[:, 0] += ux * direction[0] - uy * direction[1]
            displacement[:, 1] += ux * direction[1] + uy * direction[0]

    if character in {"screw", "mixed"}:
        screw_magnitude = float(burgers[2])
        if character == "screw" and np.isclose(screw_magnitude, 0):
            screw_magnitude = float(np.linalg.norm(burgers))
        displacement[:, 2] += screw_magnitude / (2 * np.pi) * theta
    return displacement
