"""Shared generator validation and structure operations."""

from __future__ import annotations

from typing import ClassVar

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pymatgen.core import Structure


class Supercell(BaseModel):
    model_config = ConfigDict(extra="forbid")

    matrix: tuple[
        tuple[int, int, int],
        tuple[int, int, int],
        tuple[int, int, int],
    ] = ((1, 0, 0), (0, 1, 0), (0, 0, 1))

    @field_validator("matrix")
    @classmethod
    def validate_matrix(cls, value):
        matrix = np.asarray(value, dtype=int)
        if not np.array_equal(matrix, matrix.astype(int)) or round(float(np.linalg.det(matrix))) <= 0:
            raise ValueError("supercell matrix must have a positive integer determinant")
        return tuple(tuple(int(item) for item in row) for row in matrix)


def apply_supercell(structure: Structure, supercell: Supercell) -> Structure:
    expanded = structure.copy()
    expanded.make_supercell(np.asarray(supercell.matrix, dtype=int))
    return expanded
