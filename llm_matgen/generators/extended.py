"""Validation helpers shared by extended structure generators."""

from __future__ import annotations

from math import gcd
from typing import TypeAlias

from pymatgen.core import Structure

MillerIndex: TypeAlias = tuple[int, int, int]


def normalize_miller(index: MillerIndex) -> MillerIndex:
    """Reduce a Miller index while retaining its physical sign convention."""
    if len(index) != 3 or not any(index):
        raise ValueError("Miller index must contain three integers and be non-zero")
    divisor = gcd(gcd(abs(index[0]), abs(index[1])), abs(index[2]))
    return tuple(int(value // divisor) for value in index)  # type: ignore[return-value]


def estimate_structure_size(
    structure: Structure,
    repetitions: tuple[int, int, int] = (1, 1, 1),
) -> int:
    """Estimate atom count from material repetitions; vacuum adds no atoms."""
    if len(repetitions) != 3 or any(value <= 0 for value in repetitions):
        raise ValueError("repetitions must contain three positive integers")
    return len(structure) * repetitions[0] * repetitions[1] * repetitions[2]
