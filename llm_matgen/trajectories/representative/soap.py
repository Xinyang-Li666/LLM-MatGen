"""DScribe SOAP backend (optional dependency)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from llm_matgen.trajectories.filtering.models import FilterFrame
from .config import SOAPConfig


@dataclass(frozen=True)
class SOAPPoolingResult:
    values: np.ndarray
    names: tuple[str, ...]
    presence: tuple[bool, ...]


def pool_local_soap(
    local: np.ndarray,
    atomic_numbers: np.ndarray,
    groups: dict[str, tuple[int, ...]],
    *,
    pooling: str = "category-mean-std",
) -> SOAPPoolingResult:
    local = np.asarray(local, dtype=float)
    numbers = np.asarray(atomic_numbers, dtype=int)
    if local.ndim != 2 or local.shape[0] != numbers.size or not np.isfinite(local).all():
        raise ValueError("local SOAP must be finite with one row per atom")
    if pooling not in {"category-mean-std", "mean-std", "mean"}:
        raise ValueError("unsupported SOAP pooling")
    ordered = tuple(groups.items())
    values: list[float] = []
    names: list[str] = []
    presence: list[bool] = []
    for category, elements in ordered:
        mask = np.isin(numbers, elements)
        presence.append(bool(mask.any()))
        if mask.any():
            mean = np.mean(local[mask], axis=0)
            std = np.std(local[mask], axis=0, ddof=0)
        else:
            mean = np.zeros(local.shape[1])
            std = np.zeros(local.shape[1])
        if pooling in {"category-mean-std", "mean-std"}:
            values.extend(mean.tolist()); names.extend(f"{category}:mean:{i}" for i in range(local.shape[1]))
            values.extend(std.tolist()); names.extend(f"{category}:std:{i}" for i in range(local.shape[1]))
        else:
            values.extend(mean.tolist()); names.extend(f"{category}:mean:{i}" for i in range(local.shape[1]))
    for category, present in zip((name for name, _ in ordered), presence):
        values.append(float(present)); names.append(f"{category}:present")
    return SOAPPoolingResult(np.asarray(values, dtype=np.float32), tuple(names), tuple(presence))


class SOAPDescriptorBackend:
    def __init__(self, species: Iterable[int], config: SOAPConfig | None = None):
        try:
            from dscribe.descriptors import SOAP
        except ImportError as exc:
            raise RuntimeError("install optional dependency with `pip install llm-matgen[soap]`") from exc
        self.species = tuple(sorted({int(z) for z in species}))
        self.config = config or SOAPConfig()
        if not self.species:
            raise ValueError("SOAP species cannot be empty")
        compression = {"mode": self.config.compression}
        self._descriptor = SOAP(
            r_cut=self.config.r_cut, n_max=self.config.n_max, l_max=self.config.l_max,
            sigma=self.config.sigma, rbf=self.config.rbf, compression=compression,
            species=list(self.species), periodic=self.config.periodic, dtype=self.config.dtype,
        )
        self._feature_count = int(self._descriptor.get_number_of_features())
        if self.config.groups:
            self.groups = dict(self.config.groups)
        else:
            self.groups = {
                "TM": tuple(z for z in self.species if z not in {5, 6, 8}),
                "B": tuple(z for z in self.species if z == 5),
                "C": tuple(z for z in self.species if z == 6),
                "O": tuple(z for z in self.species if z == 8),
            }

    @property
    def feature_names(self) -> tuple[str, ...]:
        return tuple(f"soap:{index}" for index in range(self._feature_count))

    def describe_local(self, frame: FilterFrame) -> np.ndarray:
        actual = set(int(value) for value in frame.atomic_numbers)
        if not actual.issubset(self.species):
            raise ValueError(f"frame species {sorted(actual - set(self.species))} are outside SOAP species")
        if self.config.periodic and (frame.cell is None or not np.any(frame.pbc)):
            raise ValueError("periodic SOAP requires a valid cell and PBC")
        from ase import Atoms

        atoms = Atoms(numbers=frame.atomic_numbers, positions=frame.positions, cell=frame.cell, pbc=frame.pbc)
        values = np.asarray(self._descriptor.create(atoms), dtype=np.float32)
        norms = np.linalg.norm(values, axis=1, keepdims=True)
        np.divide(values, norms, out=values, where=norms > 0)
        return values

    def describe(self, frame: FilterFrame) -> np.ndarray:
        local = self.describe_local(frame)
        pooled = pool_local_soap(local, frame.atomic_numbers, self.groups, pooling=self.config.pooling)
        return pooled.values
