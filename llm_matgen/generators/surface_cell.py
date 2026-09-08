"""Deterministic integer-cell shaping helpers for surface slabs."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

import numpy as np


SEARCH_COEFFICIENT_LIMIT = 8


@dataclass(frozen=True)
class InplaneTransform:
    matrix: tuple[tuple[int, int], tuple[int, int]]
    lattice_angles: tuple[float, float, float]
    area_multiplier: int
    inplane_aspect_ratio: float
    total_angle_error: float
    strict: bool


def lattice_angle(first: np.ndarray, second: np.ndarray) -> float:
    """Return the angle between two finite, non-zero Cartesian vectors."""
    first = np.asarray(first, dtype=float)
    second = np.asarray(second, dtype=float)
    if (
        first.ndim != 1
        or second.ndim != 1
        or not np.isfinite(first).all()
        or not np.isfinite(second).all()
        or np.linalg.norm(first) <= 1e-12
        or np.linalg.norm(second) <= 1e-12
    ):
        raise ValueError("lattice vectors must be finite non-zero vectors")
    cosine = np.dot(first, second) / (np.linalg.norm(first) * np.linalg.norm(second))
    return float(np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0))))


def lattice_angles(matrix: np.ndarray) -> tuple[float, float, float]:
    """Return pymatgen-style (alpha, beta, gamma) angles."""
    matrix = np.asarray(matrix, dtype=float)
    if matrix.shape != (3, 3) or not np.isfinite(matrix).all():
        raise ValueError("lattice matrix must be a finite 3x3 array")
    return (
        lattice_angle(matrix[1], matrix[2]),
        lattice_angle(matrix[0], matrix[2]),
        lattice_angle(matrix[0], matrix[1]),
    )


def orthogonalize_c_axis(slab):
    """Return a slab with c perpendicular to its in-plane vectors."""
    method = getattr(slab, "get_orthogonal_c_slab", None)
    if method is None:
        raise RuntimeError(
            "pymatgen slab does not support get_orthogonal_c_slab; "
            "near-orthogonal surface cells are unavailable"
        )
    result = method()
    matrix = np.asarray(result.lattice.matrix, dtype=float)
    if not np.isfinite(matrix).all():
        raise RuntimeError("c-axis orthogonalization returned a non-finite lattice")
    return result


def _candidate_key(candidate: InplaneTransform) -> tuple:
    p, q = candidate.matrix[0]
    r, s = candidate.matrix[1]
    identity_distance = abs(p - 1) + abs(q) + abs(r) + abs(s - 1)
    return (
        candidate.area_multiplier,
        round(candidate.inplane_aspect_ratio, 12),
        round(candidate.total_angle_error, 12),
        identity_distance,
        p,
        q,
        r,
        s,
    )


def find_inplane_transform(
    slab,
    *,
    max_area: int,
    tolerance: float,
    coefficient_limit: int = SEARCH_COEFFICIENT_LIMIT,
) -> InplaneTransform:
    """Find a deterministic integer in-plane transform near 90-degree angles."""
    if max_area < 1:
        raise ValueError("max_area must be positive")
    if tolerance <= 0 or not np.isfinite(tolerance):
        raise ValueError("tolerance must be a positive finite number")
    lattice = np.asarray(slab.lattice.matrix, dtype=float)
    if lattice.shape != (3, 3) or not np.isfinite(lattice).all():
        raise ValueError("slab lattice must be a finite 3x3 array")
    a_vec, b_vec, c_vec = lattice
    if any(np.linalg.norm(vector) <= 1e-12 for vector in lattice):
        raise ValueError("slab lattice vectors must be finite non-zero vectors")

    candidates: list[InplaneTransform] = []
    values = range(-coefficient_limit, coefficient_limit + 1)
    for p in values:
        for q in values:
            a_new = p * a_vec + q * b_vec
            if np.linalg.norm(a_new) <= 1e-12:
                continue
            for r in values:
                for s in values:
                    determinant = p * s - q * r
                    if determinant < 1 or determinant > max_area:
                        continue
                    b_new = r * a_vec + s * b_vec
                    if np.linalg.norm(b_new) <= 1e-12:
                        continue
                    angles = (
                        lattice_angle(b_new, c_vec),
                        lattice_angle(a_new, c_vec),
                        lattice_angle(a_new, b_new),
                    )
                    total_error = float(sum(abs(angle - 90.0) for angle in angles))
                    lengths = (float(np.linalg.norm(a_new)), float(np.linalg.norm(b_new)))
                    aspect_ratio = max(lengths) / min(lengths)
                    candidates.append(
                        InplaneTransform(
                            matrix=((int(p), int(q)), (int(r), int(s))),
                            lattice_angles=angles,
                            area_multiplier=int(determinant),
                            inplane_aspect_ratio=aspect_ratio,
                            total_angle_error=total_error,
                            strict=all(abs(angle - 90.0) <= tolerance for angle in angles),
                        )
                    )

    if not candidates:
        raise RuntimeError("no valid in-plane integer supercell transform found")
    strict = [candidate for candidate in candidates if candidate.strict]
    pool = strict or candidates
    if strict:
        return min(pool, key=_candidate_key)
    return min(
        pool,
        key=lambda candidate: (
            round(candidate.total_angle_error, 12),
            *_candidate_key(candidate),
        ),
    )


def apply_inplane_transform(slab, transform: InplaneTransform):
    """Apply one 2x2 transform while keeping the c-direction unchanged."""
    matrix = np.eye(3, dtype=int)
    matrix[:2, :2] = np.asarray(transform.matrix, dtype=int)
    result = deepcopy(slab)
    result.make_supercell(matrix)
    return result


def measure_slab_dimensions(slab) -> tuple[float, float]:
    """Return atom projection span and non-negative periodic vacuum along c."""
    c_vector = np.asarray(slab.lattice.matrix[2], dtype=float)
    c_length = float(np.linalg.norm(c_vector))
    if c_length <= 1e-12 or len(slab) == 0:
        return 0.0, max(c_length, 0.0)
    c_unit = c_vector / c_length
    projections = np.dot(np.asarray(slab.cart_coords, dtype=float), c_unit)
    span = float(np.max(projections) - np.min(projections))
    return span, max(c_length - span, 0.0)
