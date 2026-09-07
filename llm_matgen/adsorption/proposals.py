"""Deterministic adsorption site and pose proposals."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from itertools import combinations, product
from typing import Iterable, Sequence

import numpy as np
from pymatgen.analysis.adsorption import AdsorbateSiteFinder
from pymatgen.core import Molecule, Structure


def _unit(vector: np.ndarray) -> np.ndarray:
    vector = np.asarray(vector, dtype=float)
    if vector.shape != (3,) or not np.isfinite(vector).all():
        raise ValueError("vector must contain three finite values")
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
    pose_transform: "PoseTransform | None" = None

    def __post_init__(self) -> None:
        coords = np.asarray(self.adsorbate_coords, dtype=float)
        if coords.ndim != 2 or coords.shape[1] != 3 or not np.isfinite(coords).all():
            raise ValueError("adsorbate_coords must be a finite N x 3 array")
        object.__setattr__(self, "adsorbate_coords", coords)


@dataclass(frozen=True)
class PoseTransform:
    rotation: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]
    translation: tuple[float, float, float]
    azimuth: float
    tilt: float
    roll: float


def _axis_angle(axis: np.ndarray, angle: float) -> np.ndarray:
    axis = _unit(axis)
    x, y, z = axis
    skew = np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
    return np.eye(3) + math.sin(angle) * skew + (1.0 - math.cos(angle)) * (skew @ skew)


def _align_rotation(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    source = _unit(source)
    target = _unit(target)
    cross = np.cross(source, target)
    sine = float(np.linalg.norm(cross))
    cosine = float(np.clip(np.dot(source, target), -1.0, 1.0))
    if sine > 1e-12:
        return _axis_angle(cross / sine, math.atan2(sine, cosine))
    if cosine > 0:
        return np.eye(3)
    basis = np.eye(3)[int(np.argmin(np.abs(source)))]
    return _axis_angle(_unit(np.cross(source, basis)), math.pi)


def place_adsorbate_rigid(
    molecule: Molecule,
    anchor_zero_based: int,
    reference_axis: Sequence[float],
    frame: SurfaceFrame,
    height: float,
    azimuth: float,
    tilt: float,
    roll: float = 0.0,
) -> tuple[Molecule, PoseTransform]:
    """Place a rigid adsorbate around its anchor in a local surface frame."""
    if not 0 <= anchor_zero_based < len(molecule):
        raise ValueError("anchor index is outside adsorbate")
    values = (height, azimuth, tilt, roll)
    if not all(math.isfinite(float(value)) for value in values):
        raise ValueError("pose values must be finite")
    normal = np.asarray(frame.normal, dtype=float)
    tangent_u = np.asarray(frame.basis_u, dtype=float)
    tangent_v = np.asarray(frame.basis_v, dtype=float)
    azimuth_rad = math.radians(float(azimuth))
    tilt_rad = math.radians(float(tilt))
    inplane = math.cos(azimuth_rad) * tangent_u + math.sin(azimuth_rad) * tangent_v
    target_axis = math.cos(tilt_rad) * normal + math.sin(tilt_rad) * inplane
    rotation = _align_rotation(np.asarray(reference_axis, dtype=float), target_axis)
    if abs(float(roll)) > 1e-15:
        rotation = _axis_angle(target_axis, math.radians(float(roll))) @ rotation
    coordinates = np.asarray(molecule.cart_coords, dtype=float)
    relative = coordinates - coordinates[anchor_zero_based]
    target = np.asarray(frame.origin, dtype=float) + float(height) * normal
    placed_coords = relative @ rotation.T + target
    placed = Molecule(
        [site.specie for site in molecule], placed_coords,
        charge=molecule.charge, spin_multiplicity=molecule.spin_multiplicity,
        site_properties=molecule.site_properties,
    )
    translation = target - coordinates[anchor_zero_based] @ rotation.T
    transform = PoseTransform(
        rotation=tuple(tuple(float(item) for item in row) for row in rotation),
        translation=tuple(float(item) for item in translation),
        azimuth=float(azimuth), tilt=float(tilt), roll=float(roll),
    )
    return placed, transform


class AlgorithmicProposalSource:
    """Generate bounded, stably ordered poses from pymatgen adsorption sites."""

    def __init__(self, slab: Structure, molecule: Molecule, *, height: float = 2.0, anchor_index: int = 0,
                 reference_axis: Sequence[float] = (0.0, 0.0, 1.0), azimuths: Sequence[float] = (0.0,),
                 tilts: Sequence[float] = (0.0,), rolls: Sequence[float] = (0.0,), heights: Sequence[float] | None = None):
        if not np.isfinite(height) or height <= 0:
            raise ValueError("height must be a finite positive number")
        if not 0 <= anchor_index < len(molecule):
            raise ValueError("anchor_index must be a valid zero-based molecule index")
        self.slab = slab
        self.molecule = molecule
        self.height = float(height)
        self.anchor_index = anchor_index
        self.reference_axis = tuple(float(item) for item in reference_axis)
        self.azimuths = tuple(float(item) for item in azimuths)
        self.tilts = tuple(float(item) for item in tilts)
        self.rolls = tuple(float(item) for item in rolls)
        self.heights = tuple(float(item) for item in (heights or (height,)))
        if not self.azimuths or not self.tilts or not self.rolls or not self.heights:
            raise ValueError("pose sets must be non-empty")
        if not all(math.isfinite(item) for item in (*self.reference_axis, *self.azimuths, *self.tilts, *self.rolls, *self.heights)):
            raise ValueError("pose sets must be finite")

    def _finder_sites(self) -> dict[str, list[np.ndarray]]:
        try:
            found = AdsorbateSiteFinder(self.slab).find_adsorption_sites()
        except Exception:
            found = {}
        sites = {
            kind: [np.asarray(site, dtype=float) for site in found.get(kind, [])]
            for kind in ("ontop", "bridge", "hollow", "hollow4")
        }
        if not sites["hollow4"]:
            frame = SurfaceFrame.from_slab(self.slab, side="top")
            normal = np.asarray(frame.normal)
            projection = np.asarray(self.slab.cart_coords) @ normal
            top = [index for index, value in enumerate(projection) if value >= float(np.max(projection)) - 0.35]
            top = sorted(top, key=lambda index: tuple(np.round(self.slab[index].coords, 8)))[:24]
            candidates = []
            for group in combinations(top, 4):
                points = np.asarray([self.slab[index].coords for index in group])
                center = points.mean(axis=0)
                distances = np.linalg.norm(points - center, axis=1)
                if float(np.std(distances)) <= 0.15 and float(np.max(distances)) > 0.0:
                    if not any(np.linalg.norm(center - previous) < 1e-6 for previous in candidates):
                        candidates.append(center)
            sites["hollow4"] = sorted(candidates, key=lambda value: tuple(np.round(value, 8)))
        return sites

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
            found_sites = self._finder_sites()
            for requested_kind in site_kinds:
                kind = "ontop" if requested_kind == "top" else requested_kind
                for index, coordinate in enumerate(found_sites.get(kind, [])):
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
                for pose_height, azimuth, tilt, roll in product(self.heights, self.azimuths, self.tilts, self.rolls):
                    pose_frame = replace(frame, origin=tuple(site.tolist()))
                    placed, transform = place_adsorbate_rigid(
                        self.molecule, self.anchor_index, self.reference_axis, pose_frame,
                        0.0 if kind == "explicit" else pose_height, azimuth, tilt, roll,
                    )
                    default_pose = len(self.heights) == len(self.azimuths) == len(self.tilts) == len(self.rolls) == 1 and not any((azimuth, tilt, roll))
                    base_id = site_id if kind == "explicit" and selected_side == "top" else f"{site_id}:{selected_side}"
                    proposal_id = base_id if default_pose else f"{base_id}:azimuth={azimuth:g}:tilt={tilt:g}:roll={roll:g}"
                    yield AdsorptionProposal(
                        site_id=proposal_id, site_kind=kind, side=selected_side,
                        cartesian_site=tuple((site + np.asarray(frame.normal) * (0.0 if kind == "explicit" else pose_height)).tolist()),
                        adsorbate_coords=np.asarray(placed.cart_coords), frame=pose_frame,
                        pose_transform=transform,
                    )


@dataclass(frozen=True)
class ProposalStreamAudit:
    attempted: int
    accepted: int
    rejected: int
    truncated: bool


def _value(item, key: str, default=None):
    return item.get(key, default) if isinstance(item, dict) else getattr(item, key, default)


class RetrievedProposalSource:
    """Replay history as local fractional poses on the current slab."""

    def __init__(self, slab: Structure, molecule: Molecule, history: Iterable, *, height: float = 2.0, anchor_index: int = 0):
        if not 0 <= anchor_index < len(molecule):
            raise ValueError("anchor_index must be a valid zero-based molecule index")
        self.slab = slab
        self.molecule = molecule
        self.history = tuple(history)
        self.height = float(height)
        self.anchor_index = anchor_index

    def iter_proposals(self) -> Iterable[AdsorptionProposal]:
        molecule_coords = np.asarray(self.molecule.cart_coords, dtype=float)
        anchor = molecule_coords[self.anchor_index]
        for item in sorted(self.history, key=lambda value: str(_value(value, "revision_id", ""))):
            revision_id = str(_value(item, "revision_id", "unknown"))
            side = str(_value(item, "side", "top"))
            if side not in {"top", "bottom"}:
                continue
            frame = SurfaceFrame.from_slab(self.slab, side=side)
            fractional = _value(item, "fractional_site")
            if fractional is None:
                continue
            site = np.asarray(self.slab.lattice.get_cartesian_coords(fractional), dtype=float)
            site_frame = replace(frame, origin=tuple(site.tolist()))
            local = _value(item, "local_adsorbate_coordinates")
            if local is not None:
                local_array = np.asarray(local, dtype=float)
                if local_array.shape != (len(self.molecule), 3) or not np.isfinite(local_array).all():
                    raise ValueError("history local pose must be a finite N x 3 array")
                delta = _value(item, "local_delta", (0.0, 0.0, 0.0))
                delta_array = np.asarray(delta, dtype=float)
                if delta_array.shape != (3,) or not np.isfinite(delta_array).all():
                    raise ValueError("history local delta must be a finite triplet")
                basis = np.vstack([frame.basis_u, frame.basis_v, frame.normal])
                coords = local_array @ basis + site + np.asarray(frame.normal) * self.height
                coords += delta_array @ basis
            else:
                coords = molecule_coords + site + np.asarray(frame.normal) * self.height - anchor
            yield AdsorptionProposal(
                site_id=f"history:{revision_id}",
                site_kind=str(_value(item, "site_kind", "history")),
                side=side,
                cartesian_site=tuple((site + np.asarray(frame.normal) * self.height).tolist()),
                adsorbate_coords=coords,
                frame=site_frame,
                source="history",
            )


def resolve_history(mode: str, history_source, fallback_source):
    if mode not in {"off", "prefer", "require"}:
        raise ValueError("history mode must be off, prefer or require")
    if mode == "off":
        return fallback_source, None
    if history_source is not None:
        try:
            resolved = history_source() if callable(history_source) else history_source
        except Exception as exc:
            if mode == "require":
                raise ValueError(f"history required but store unavailable: {exc}") from exc
            return fallback_source, f"history store unavailable; fallback to algorithmic proposals ({type(exc).__name__})"
        if resolved is not None:
            return resolved, None
    if mode == "require":
        raise ValueError("history proposals are required but unavailable")
    return fallback_source, "history unavailable; fallback to algorithmic proposals"


def bounded_proposal_stream(proposals: Iterable, secondary: Iterable | None = None, *, max_attempts: int,
                            max_accepted: int | None = None, accept=None):
    if max_attempts <= 0:
        raise ValueError("max_attempts must be positive")
    selected = []
    attempted = rejected = 0
    truncated = False
    iterators = [iter(proposals)] + ([iter(secondary)] if secondary is not None else [])
    cursor = 0
    while attempted < max_attempts:
        proposal = None
        exhausted = 0
        for _ in range(len(iterators)):
            iterator = iterators[cursor % len(iterators)]
            cursor += 1
            try:
                proposal = next(iterator)
                break
            except StopIteration:
                exhausted += 1
        if proposal is None and exhausted == len(iterators):
            break
        attempted += 1
        if proposal is None or (accept is not None and not accept(proposal)):
            rejected += 1
            continue
        selected.append(proposal)
        if max_accepted is not None and len(selected) >= max_accepted:
            break
    else:
        truncated = True
    return selected, ProposalStreamAudit(attempted, len(selected), rejected, truncated)
