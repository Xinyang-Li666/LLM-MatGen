"""Deterministic adsorption site and pose proposals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
from pymatgen.analysis.adsorption import AdsorbateSiteFinder
from pymatgen.core import Molecule, Structure


def _unit(vector: np.ndarray) -> np.ndarray:
    length = float(np.linalg.norm(vector))
    if length < 1e-12:
        raise ValueError("surface lattice vectors must define a non-zero direction")
    return vector / length


@dataclass(frozen=True)
class SurfaceFrame:
    origin: tuple[float, float, float]
    normal: tuple[float, float, float]
    basis_u: tuple[float, float, float]
    basis_v: tuple[float, float, float]
    side: str = "top"

    @classmethod
    def from_slab(cls, slab: Structure, side: str = "top") -> "SurfaceFrame":
        if side not in {"top", "bottom"}:
            raise ValueError("side must be 'top' or 'bottom'")
        normal = _unit(np.cross(np.asarray(slab.lattice.matrix[0]), np.asarray(slab.lattice.matrix[1])))
        if np.dot(normal, slab.lattice.matrix[2]) < 0:
            normal = -normal
        if side == "bottom":
            normal = -normal
        u = np.asarray(slab.lattice.matrix[0], dtype=float)
        u = u - np.dot(u, normal) * normal
        u = _unit(u)
        v = _unit(np.cross(normal, u))
        projections = np.asarray(slab.cart_coords) @ normal
        plane = float(np.max(projections) if side == "top" else np.min(projections))
        return cls(tuple((plane * normal).tolist()), tuple(normal.tolist()), tuple(u.tolist()), tuple(v.tolist()), side)


@dataclass(frozen=True)
class AdsorptionProposal:
    site_id: str
    site_kind: str
    side: str
    cartesian_site: tuple[float, float, float]
    adsorbate_coords: np.ndarray
    frame: SurfaceFrame
    source: str = "algorithmic"

    def __post_init__(self) -> None:
        coords = np.asarray(self.adsorbate_coords, dtype=float)
        if coords.ndim != 2 or coords.shape[1] != 3 or not np.isfinite(coords).all():
            raise ValueError("adsorbate_coords must be a finite N x 3 array")
        object.__setattr__(self, "adsorbate_coords", coords)


class AlgorithmicProposalSource:
    """Generate bounded, stably ordered poses from pymatgen adsorption sites."""

    def __init__(self, slab: Structure, molecule: Molecule, *, height: float = 2.0, anchor_index: int = 0):
        if not np.isfinite(height) or height <= 0:
            raise ValueError("height must be a finite positive number")
        if not 0 <= anchor_index < len(molecule):
            raise ValueError("anchor_index must be a valid zero-based molecule index")
        self.slab = slab
        self.molecule = molecule
        self.height = float(height)
        self.anchor_index = anchor_index

    def _finder_sites(self) -> dict[str, list[np.ndarray]]:
        try:
            found = AdsorbateSiteFinder(self.slab).find_adsorption_sites()
        except Exception:
            found = {}
        return {
            kind: [np.asarray(site, dtype=float) for site in found.get(kind, [])]
            for kind in ("ontop", "bridge", "hollow", "hollow4")
        }

    def iter_proposals(
        self,
        *,
        site_kinds: Sequence[str] = ("ontop", "bridge", "hollow"),
        side: str = "top",
        explicit_sites: Iterable[tuple[str, Sequence[float]]] | None = None,
    ) -> Iterable[AdsorptionProposal]:
        if side not in {"top", "bottom", "both"}:
            raise ValueError("side must be top, bottom or both")
        sides = ("top", "bottom") if side == "both" else (side,)
        molecule_coords = np.asarray(self.molecule.cart_coords, dtype=float)
        anchor = molecule_coords[self.anchor_index]
        if explicit_sites is not None:
            rows = [(str(site_id), "explicit", np.asarray(coords, dtype=float), "top") for site_id, coords in explicit_sites]
        else:
            rows = []
            for kind in site_kinds:
                for index, coordinate in enumerate(self._finder_sites().get(kind, [])):
                    rows.append((f"{kind}-{index:04d}", kind, coordinate, "top"))
        for site_id, kind, base, source_side in sorted(rows, key=lambda row: row[0]):
            for selected_side in sides:
                frame = SurfaceFrame.from_slab(self.slab, side=selected_side)
                site = np.asarray(base, dtype=float)
                if kind != "explicit":
                    if selected_side == "bottom":
                        normal_top = np.asarray(SurfaceFrame.from_slab(self.slab, side="top").normal)
                        projections = np.asarray(self.slab.cart_coords) @ normal_top
                        site = site - (float(np.dot(site, normal_top)) - float(np.min(projections))) * normal_top
                    site = site + np.asarray(frame.normal) * self.height
                coords = molecule_coords + site - anchor
                proposal_id = site_id if kind == "explicit" and selected_side == "top" else f"{site_id}:{selected_side}"
                yield AdsorptionProposal(
                    site_id=proposal_id,
                    site_kind=kind,
                    side=selected_side,
                    cartesian_site=tuple(site.tolist()),
                    adsorbate_coords=coords,
                    frame=frame,
                )
