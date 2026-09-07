"""Periodic partial-RDF descriptors for trajectory frames."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations_with_replacement, product

import numpy as np
from ase import Atoms
from ase.neighborlist import neighbor_list

from llm_matgen.trajectories.filtering.models import FilterFrame


@dataclass(frozen=True)
class RDFChannel:
    name: str
    left: tuple[int, ...]
    right: tuple[int, ...]

    def __post_init__(self) -> None:
        if not self.name or not self.left or not self.right:
            raise ValueError("RDF channels require a name and non-empty element groups")
        if any(int(z) < 1 or int(z) > 118 for z in (*self.left, *self.right)):
            raise ValueError("RDF channel atomic numbers must be between 1 and 118")


class RDFDescriptor:
    def __init__(self, channels: tuple[RDFChannel, ...], r_min: float, r_max: float, bin_width: float):
        if not channels:
            raise ValueError("at least one RDF channel is required")
        if not np.isfinite([r_min, r_max, bin_width]).all() or r_min < 0 or r_max <= r_min or bin_width <= 0:
            raise ValueError("invalid RDF range or bin width")
        bins = (r_max - r_min) / bin_width
        if not np.isclose(bins, round(bins), rtol=0, atol=1e-8):
            raise ValueError("(r_max-r_min) must be divisible by bin_width")
        self.channels = tuple(channels)
        self.r_min, self.r_max, self.bin_width = float(r_min), float(r_max), float(bin_width)
        self._bin_count = int(round(bins))

    @property
    def feature_names(self) -> tuple[str, ...]:
        return tuple(
            f"rdf:{channel.name}:r{i}"
            for channel in self.channels
            for i in range(self._bin_count)
        )

    def describe(self, frame: FilterFrame) -> np.ndarray:
        positions = np.asarray(frame.positions, dtype=float)
        if not np.isfinite(positions).all() or (frame.cell is not None and not np.isfinite(frame.cell).all()):
            raise ValueError("frame geometry must be finite")
        if frame.cell is not None and np.all(frame.pbc) and frame.natoms <= 512:
            center, neighbor, distances = _vectorized_periodic_neighbors(positions, frame.cell, self.r_max)
        else:
            atoms = Atoms(
                numbers=frame.atomic_numbers.tolist(), positions=positions,
                cell=np.zeros((3, 3)) if frame.cell is None else frame.cell,
                pbc=frame.pbc,
            )
            center, neighbor, distances = neighbor_list("ijd", atoms, self.r_max)
        result = np.zeros((len(self.channels), self._bin_count), dtype=float)
        volume = abs(float(np.linalg.det(frame.cell))) if frame.cell is not None and np.any(frame.pbc) else None
        numbers = frame.atomic_numbers
        for channel_index, channel in enumerate(self.channels):
            left_mask = np.isin(numbers[center], channel.left)
            right_mask = np.isin(numbers[neighbor], channel.right)
            selected = left_mask & right_mask & (distances >= self.r_min) & (distances < self.r_max)
            if not np.any(selected):
                continue
            bins = np.floor((distances[selected] - self.r_min) / self.bin_width).astype(int)
            counts = np.bincount(bins, minlength=self._bin_count)[: self._bin_count]
            n_left = int(np.isin(numbers, channel.left).sum())
            n_right = int(np.isin(numbers, channel.right).sum())
            shell = 4.0 * np.pi / 3.0 * (
                (self.r_min + (np.arange(self._bin_count) + 1) * self.bin_width) ** 3
                - (self.r_min + np.arange(self._bin_count) * self.bin_width) ** 3
            )
            if volume is not None and volume > 0:
                result[channel_index] = counts / (n_left * shell * (n_right / volume))
            else:
                result[channel_index] = counts / (n_left * shell)
        return result.ravel()


def build_hybrid_channels(atomic_numbers: tuple[int, ...] | list[int]) -> tuple[RDFChannel, ...]:
    elements = tuple(sorted({int(z) for z in atomic_numbers}))
    return tuple(
        RDFChannel(f"{left}-{right}", (left,), (right,))
        for left, right in combinations_with_replacement(elements, 2)
    )


def _vectorized_periodic_neighbors(
    positions: np.ndarray,
    cell: np.ndarray,
    cutoff: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Exact small-cell periodic neighbors without ASE cell-list overhead."""
    fractional = np.linalg.solve(cell.T, positions.T).T
    fractional %= 1.0
    wrapped = fractional @ cell
    reciprocal = np.linalg.pinv(cell).T
    face_distances = 1.0 / np.linalg.norm(reciprocal, axis=1)
    limits = np.ceil(cutoff / face_distances).astype(int)
    center_parts: list[np.ndarray] = []
    neighbor_parts: list[np.ndarray] = []
    distance_parts: list[np.ndarray] = []
    cutoff2 = cutoff * cutoff
    for coefficients in product(*(range(-limit, limit + 1) for limit in limits)):
        shift = np.asarray(coefficients, dtype=float) @ cell
        delta = wrapped[None, :, :] + shift - wrapped[:, None, :]
        distance2 = np.einsum("ijk,ijk->ij", delta, delta)
        if not any(coefficients):
            np.fill_diagonal(distance2, np.inf)
        mask = distance2 < cutoff2
        centers, neighbors = np.nonzero(mask)
        if centers.size:
            center_parts.append(centers)
            neighbor_parts.append(neighbors)
            distance_parts.append(np.sqrt(distance2[centers, neighbors]))
    if not center_parts:
        empty_i = np.empty(0, dtype=int)
        return empty_i, empty_i.copy(), np.empty(0, dtype=float)
    return np.concatenate(center_parts), np.concatenate(neighbor_parts), np.concatenate(distance_parts)
