"""Trajectory quality filtering.

Detects non-physical structures in MD trajectories via frame-level classification
across multiple dimensions, then separates frames into clean and anomalous output.

Dimensions:
  1. Hard overlap      — element-pair minimum distance violations
  2. Force magnitude   — per-atom force extremes (per-model hard threshold)
  3. Group-averaged    — mean coordination per element group, IQR outlier
     coordination        detection referenced against a clean trajectory

Usage::

    from llm_matgen.trajectories.filter import FilterConfig, filter_trajectory

    config = FilterConfig(
        dimensions=("overlap", "force", "coordination"),
        force_thresholds={"my_model": 20.0},
        coord_groups={"cation": [22, 40, 72], "anion": [5, 6, 8]},
    )
    result = filter_trajectory(
        Path("md.dump"), Path("output"), config,
        reference_path=Path("reference.dump"),
        model_name="my_model",
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from collections import defaultdict
from typing import Any
import numpy as np

# ─────────────────────────────────────────────────────────
# Data models
# ─────────────────────────────────────────────────────────

@dataclass
class RawFrame:
    """Single trajectory frame with raw numerical arrays.

    Carries positions, forces, and cell directly as numpy arrays so that
    feature computation (overlap detection, coordination) can run without
    intermediate pymatgen/ASE conversions.
    """
    positions: np.ndarray       # (natoms, 3)
    types: np.ndarray           # (natoms,)  atomic numbers
    forces: np.ndarray | None   # (natoms, 3) or None
    cell: np.ndarray | None     # (3, 3)      or None
    periodic: bool
    timestep: int
    bounds: list[tuple[float, float]] = field(default_factory=list)

    @property
    def natoms(self) -> int:
        return len(self.positions)


@dataclass
class FilterConfig:
    """Configuration for trajectory quality filtering.

    Attributes:
        dimensions:
            Which filter dimensions to apply.  Any subset of
            ``("overlap", "force", "coordination")``.
        overlap_ratio:
            Fraction of atoms with at least one hard overlap that must be
            exceeded for the whole frame to be flagged.
        overlap_min_dist:
            Custom element-pair ``(z1, z2) → min_dist`` overrides.  When
            ``None``, sensible defaults based on covalent radii and
            metal / non-metal categories are used.
        force_thresholds:
            Per-model-name → absolute force ceiling (eV/A).  A frame whose
            maximum per-atom force exceeds the value for *model_name* is
            flagged.  If a name is missing, the force dimension is skipped.
        coord_cutoff:
            Neighbour cutoff radius in Angstrom used for coordination counting.
        coord_groups:
            Named groups of atomic numbers for which per-frame average
            coordination is computed.  Example::

                {"cation": [22, 40, 72], "anion": [5, 6, 8]}

            When *None* the code auto-detects metals (Z ≥ 21) vs non-metals
            from the atomic types present in the reference trajectory.
        n_iqr:
            IQR multiplier for outlier detection on coordination averages.
        sample_n:
            Number of equally-spaced reference frames to sample for IQR
            calibration.
    """
    dimensions: tuple[str, ...] = ("overlap", "force", "coordination")
    overlap_ratio: float = 0.10
    overlap_min_dist: dict[tuple[int, int], float] | None = None
    force_thresholds: dict[str, float] | None = None
    coord_cutoff: float = 3.5
    coord_groups: dict[str, list[int]] | None = None
    n_iqr: float = 3.0
    sample_n: int = 300


@dataclass
class FilterResult:
    """Aggregate statistics returned by :func:`filter_trajectory`."""
    total: int
    clean: int
    anomalous: int
    reasons: dict[str, int]
    thresholds: dict[str, Any]
    min_dist: float
    max_force: float
    clean_path: Path | None = None
    anomalous_path: Path | None = None


# ─────────────────────────────────────────────────────────
# Default parameters
# ─────────────────────────────────────────────────────────

_COVALENT_RADII: dict[int, float] = {
    1: 0.31,   5: 0.84,   6: 0.76,   7: 0.71,   8: 0.66,   9: 0.57,
    13: 1.21, 14: 1.11, 15: 1.07, 16: 1.05, 17: 1.02,
    21: 1.70, 22: 1.60, 23: 1.53, 24: 1.39, 25: 1.39, 26: 1.32,
    27: 1.26, 28: 1.24, 29: 1.32, 30: 1.22,
    39: 1.90, 40: 1.75, 41: 1.64, 42: 1.54, 43: 1.47,
    44: 1.46, 45: 1.42, 46: 1.39, 47: 1.45, 48: 1.77,
    57: 2.07, 72: 1.75, 73: 1.70, 74: 1.62, 75: 1.51,
    76: 1.44, 77: 1.41, 78: 1.36, 79: 1.36, 80: 1.32,
}

_METAL_THRESHOLD: int = 21  # Sc (Z=21) and above are treated as metals

_HARD_MIN_DIST: dict[tuple[int, int], float] = {
    (5, 5): 1.0, (5, 6): 1.0, (5, 7): 1.0, (5, 8): 1.0,
    (6, 8): 1.0, (8, 8): 1.2,
}

# ─────────────────────────────────────────────────────────
# Element-pair minimum distance
# ─────────────────────────────────────────────────────────

def _get_min_dist(z1: int, z2: int,
                  custom: dict[tuple[int, int], float] | None = None) -> float:
    """Return the minimum allowed interatomic distance for an element pair."""
    pair = (min(z1, z2), max(z1, z2))
    if custom is not None and pair in custom:
        return custom[pair]
    if pair in _HARD_MIN_DIST:
        return _HARD_MIN_DIST[pair]
    is_metal_1 = z1 >= _METAL_THRESHOLD
    is_metal_2 = z2 >= _METAL_THRESHOLD
    if is_metal_1 and is_metal_2:
        return 1.8
    if is_metal_1 or is_metal_2:
        return 1.3
    # Both non-metals: 60 % of covalent radius sum
    r1 = _COVALENT_RADII.get(z1, 1.3)
    r2 = _COVALENT_RADII.get(z2, 1.3)
    return max(0.7, 0.6 * (r1 + r2))


# ─────────────────────────────────────────────────────────
# Raw trajectory readers
# ─────────────────────────────────────────────────────────

def read_lammps_dump(path: Path,
                     type_map: dict[int, int] | None = None) -> list[RawFrame]:
    """Read a LAMMPS dump text file into :class:`RawFrame` objects.

    Parameters:
        path: Path to the dump file.
        type_map: Optional mapping from LAMMPS type IDs to atomic numbers.
            When *None*, type IDs are used as-is (they should already be
            atomic numbers).
    """
    frames: list[RawFrame] = []
    with open(path, encoding="utf-8") as fh:
        lines = iter(fh)
        while True:
            # Scan for ITEM: TIMESTEP
            try:
                for line in lines:
                    if line.startswith("ITEM: TIMESTEP"):
                        break
                else:
                    break
            except StopIteration:
                break

            timestep = int(next(lines))
            next(lines)  # ITEM: NUMBER OF ATOMS
            natoms = int(next(lines))

            # Box bounds
            box_line = next(lines)
            parts = box_line.split()
            periodic = [p.startswith("p") for p in parts[3:6]] if len(parts) > 5 else [True] * 3
            bounds: list[tuple[float, float]] = []
            for _ in range(3):
                bv = next(lines).split()
                bounds.append((float(bv[0]), float(bv[1])))

            # Atom header
            header = next(lines)
            cols = header.replace("ITEM: ATOMS ", "").split()
            has_f = all(c in cols for c in ["fx", "fy", "fz"])
            ic = {c: i for i, c in enumerate(cols)}

            pos = np.zeros((natoms, 3))
            types_r = np.zeros(natoms, dtype=int)
            fcs = np.zeros((natoms, 3)) if has_f else None

            for i in range(natoms):
                v = next(lines).split()
                types_r[i] = int(v[ic["type"]])
                pos[i] = [float(v[ic["x"]]), float(v[ic["y"]]), float(v[ic["z"]])]
                if has_f:
                    fcs[i] = [float(v[ic["fx"]]), float(v[ic["fy"]]), float(v[ic["fz"]])]

            # Map type IDs → atomic numbers
            if type_map is not None:
                types_a = np.array([type_map.get(int(t), int(t)) for t in types_r], dtype=int)
            else:
                types_a = types_r

            cell = np.diag([
                bounds[0][1] - bounds[0][0],
                bounds[1][1] - bounds[1][0],
                bounds[2][1] - bounds[2][0],
            ])
            is_periodic = all(periodic) and cell is not None

            frames.append(RawFrame(
                positions=pos, types=types_a, forces=fcs,
                cell=cell, periodic=is_periodic,
                timestep=timestep, bounds=bounds,
            ))
    return frames


def read_extxyz(path: Path) -> list[RawFrame]:
    """Read an extended XYZ file into :class:`RawFrame` objects.

    Expects the ``extxyz`` convention where the comment line carries
    ``Lattice="..."`` and per-atom lines contain species (column 0),
    x y z (columns 1-3), atomic number (column 5), and optionally
    forces (columns 9-11).
    """
    frames: list[RawFrame] = []
    with open(path, encoding="utf-8") as fh:
        lines = iter(fh)
        while True:
            try:
                nl = next(lines).strip()
                while nl == "" or not nl.split()[0].lstrip("-").isdigit():
                    nl = next(lines).strip()
            except StopIteration:
                break

            natoms = int(nl)
            comment = next(lines)
            has_f = "forces:R:3" in comment
            lattice = None
            if 'Lattice="' in comment:
                v = list(map(float, comment.split('Lattice="')[1].split('"')[0].split()))
                lattice = np.array(v).reshape(3, 3)

            pos = np.zeros((natoms, 3))
            types_a = np.zeros(natoms, dtype=int)
            fcs = np.zeros((natoms, 3)) if has_f else None

            for i in range(natoms):
                v = next(lines).split()
                pos[i] = [float(v[1]), float(v[2]), float(v[3])]
                types_a[i] = int(v[5])
                if has_f and len(v) >= 12:
                    fcs[i] = [float(v[9]), float(v[10]), float(v[11])]

            # Try to extract step from comment
            step = 0
            for token in comment.split():
                if token.startswith("step="):
                    step = int(token.split("=")[1])

            diag = np.diag(lattice) if lattice is not None else np.full(3, 10.0)
            bnds = [(0.0, float(d)) for d in diag]

            frames.append(RawFrame(
                positions=pos, types=types_a, forces=fcs,
                cell=lattice, periodic=True,
                timestep=step, bounds=bnds,
            ))
    return frames


# ─────────────────────────────────────────────────────────
# Feature computation
# ─────────────────────────────────────────────────────────

def compute_frame_features(frame: RawFrame,
                           config: FilterConfig) -> dict[str, Any]:
    """Compute all screening features for a single frame.

    Returns a dict with keys:
        ``n_overlap``, ``max_force``, ``coord`` (per-atom array),
        ``nn_dist`` (per-atom), ``avg_coord_<group>`` for each group,
        ``types``.
    """
    natoms = frame.natoms
    pos = frame.positions
    cell = frame.cell
    is_periodic = frame.periodic
    forces = frame.forces

    # --- Distance matrix (minimum image convention) ---
    if is_periodic and cell is not None:
        diag = np.diag(cell)
        diff = pos[:, None, :] - pos[None, :, :]
        diff -= np.round(diff / diag[None, None, :]) * diag[None, None, :]
        dist_mat = np.sqrt(np.sum(diff ** 2, axis=-1))
        np.fill_diagonal(dist_mat, np.inf)
    else:
        # Non-periodic: use full O(N²) without image correction
        diff = pos[:, None, :] - pos[None, :, :]
        dist_mat = np.sqrt(np.sum(diff ** 2, axis=-1))
        np.fill_diagonal(dist_mat, np.inf)

    # --- 1. Hard overlap ---
    n_overlap = 0
    for i in range(natoms):
        zi = int(frame.types[i])
        row = dist_mat[i]
        order = np.argpartition(row, min(10, natoms - 1))[:10]
        for j in order:
            d = row[j]
            if d > 3.0:
                break
            if i == j:
                continue
            zj = int(frame.types[j])
            if d < _get_min_dist(zi, zj, config.overlap_min_dist):
                n_overlap += 1
                break

    # --- 2. Force magnitude ---
    max_force = float(np.linalg.norm(forces, axis=1).max()) if forces is not None else 0.0

    # --- 3. Coordination ---
    coord = (dist_mat < config.coord_cutoff).sum(axis=1)

    # --- Nearest-neighbour distances (informational) ---
    nn_dist = dist_mat.min(axis=1)

    result: dict[str, Any] = {
        "n_overlap": n_overlap,
        "max_force": max_force,
        "coord": coord,
        "nn_dist": nn_dist,
        "types": frame.types,
    }
    return result


# ─────────────────────────────────────────────────────────
# IQR threshold helpers
# ─────────────────────────────────────────────────────────

def _iqr_bounds(data: np.ndarray, n_iqr: float = 3.0) -> tuple[float, float]:
    """Return (Q1 - n*IQR, Q3 + n*IQR) for a 1-D array."""
    q1, q3 = np.percentile(data, [25, 75])
    iqr = q3 - q1
    return float(q1 - n_iqr * iqr), float(q3 + n_iqr * iqr)


def _auto_detect_groups(types: np.ndarray) -> dict[str, list[int]]:
    """Auto-detect metal / non-metal groups from the atomic types present."""
    unique = sorted(set(int(t) for t in types))
    metals = [z for z in unique if z >= _METAL_THRESHOLD]
    nonmetals = [z for z in unique if z < _METAL_THRESHOLD]
    groups: dict[str, list[int]] = {}
    if metals:
        groups["cation"] = metals
    if nonmetals:
        groups["anion"] = nonmetals
    if not groups:
        groups["all"] = unique
    return groups


# ─────────────────────────────────────────────────────────
# Threshold establishment
# ─────────────────────────────────────────────────────────

def establish_thresholds(reference_frames: list[RawFrame],
                         config: FilterConfig) -> dict[str, Any]:
    """Calibrate IQR coordination thresholds from a *reference* trajectory.

    The reference should be a clean trajectory (e.g. DPA-4).  The returned
    thresholds dict can be passed to :func:`classify_and_write`.
    """
    groups = config.coord_groups
    coord_samples: dict[str, list[float]] = defaultdict(list)

    n_sample = min(config.sample_n, len(reference_frames))
    indices = np.linspace(0, len(reference_frames) - 1, n_sample, dtype=int)

    for idx in indices:
        f = reference_frames[idx]
        feats = compute_frame_features(f, config)
        coord = feats["coord"]
        types_arr = feats["types"]

        # Auto-detect groups on first use if not provided
        if groups is None:
            groups = _auto_detect_groups(types_arr)

        for grp_name, grp_zs in groups.items():
            mask = np.isin(types_arr, grp_zs)
            if mask.any():
                coord_samples[grp_name].append(float(coord[mask].mean()))

    thresholds: dict[str, Any] = {}
    for grp_name, vals in coord_samples.items():
        lo, hi = _iqr_bounds(np.array(vals), config.n_iqr)
        thresholds[grp_name] = (lo, hi)

    return thresholds


# ─────────────────────────────────────────────────────────
# Classification and output
# ─────────────────────────────────────────────────────────

def _write_lammps_frame(fh, frame: RawFrame) -> None:
    """Write a single frame in LAMMPS dump format (id type x y z only)."""
    fh.write(f"ITEM: TIMESTEP\n{frame.timestep}\n")
    fh.write(f"ITEM: NUMBER OF ATOMS\n{frame.natoms}\n")
    fh.write("ITEM: BOX BOUNDS pp pp pp\n")
    for lo, hi in frame.bounds:
        fh.write(f"{lo:.16e} {hi:.16e}\n")
    fh.write("ITEM: ATOMS id type x y z\n")
    for i in range(frame.natoms):
        fh.write(
            f"{i + 1} {frame.types[i]} "
            f"{frame.positions[i, 0]:.6f} "
            f"{frame.positions[i, 1]:.6f} "
            f"{frame.positions[i, 2]:.6f}\n"
        )


def classify_and_write(frames: list[RawFrame],
                       thresholds: dict[str, Any],
                       config: FilterConfig,
                       clean_path: Path,
                       anom_path: Path,
                       model_name: str = "") -> dict[str, Any]:
    """Classify every frame and write two output trajectories.

    Returns a stats dict compatible with :class:`FilterResult`.
    """
    groups = config.coord_groups
    force_hard = (config.force_thresholds or {}).get(model_name)

    stats: dict[str, Any] = {
        "total": 0, "clean": 0, "anom": 0,
        "overlap": 0, "force": 0, "multi": 0,
    }
    # Per-group counters
    for grp_name in thresholds:
        stats[grp_name] = 0

    min_dist_all = float("inf")
    max_force_all = 0.0

    with open(clean_path, "w", encoding="utf-8") as fc, \
         open(anom_path, "w", encoding="utf-8") as fa:

        for frame in frames:
            feats = compute_frame_features(frame, config)
            stats["total"] += 1
            natoms = frame.natoms

            if feats["nn_dist"].min() < min_dist_all:
                min_dist_all = feats["nn_dist"].min()
            if feats["max_force"] > max_force_all:
                max_force_all = feats["max_force"]

            reasons: list[str] = []

            # --- Overlap ---
            if "overlap" in config.dimensions:
                if feats["n_overlap"] / natoms > config.overlap_ratio:
                    reasons.append("overlap")

            # --- Force ---
            if "force" in config.dimensions and force_hard is not None:
                if feats["max_force"] > force_hard:
                    reasons.append("force")

            # --- Coordination ---
            if "coordination" in config.dimensions:
                coord = feats["coord"]
                types_arr = feats["types"]

                if groups is None:
                    groups = _auto_detect_groups(types_arr)

                for grp_name, grp_zs in groups.items():
                    if grp_name not in thresholds:
                        continue
                    mask = np.isin(types_arr, grp_zs)
                    if not mask.any():
                        continue
                    avg = float(coord[mask].mean())
                    lo, hi = thresholds[grp_name]
                    if avg < lo or avg > hi:
                        reasons.append(grp_name)

            # --- Decide ---
            is_anom = len(reasons) > 0
            if is_anom:
                stats["anom"] += 1
                if len(reasons) == 1:
                    r = reasons[0]
                    stats[r] = stats.get(r, 0) + 1
                else:
                    stats["multi"] += 1
                _write_lammps_frame(fa, frame)
            else:
                stats["clean"] += 1
                _write_lammps_frame(fc, frame)

    stats["min_dist"] = min_dist_all
    stats["max_force"] = max_force_all
    return stats


# ─────────────────────────────────────────────────────────
# Top-level orchestration
# ─────────────────────────────────────────────────────────

def filter_trajectory(input_path: Path,
                      output_dir: Path,
                      config: FilterConfig | None = None,
                      *,
                      reference_path: Path | None = None,
                      model_name: str = "",
                      type_map: dict[int, int] | None = None,
                      input_format: str | None = None) -> FilterResult:
    """Run quality filtering on a trajectory and write clean + anomalous outputs.

    Parameters:
        input_path:
            Path to the trajectory file to filter.
        output_dir:
            Directory for the two output dump files
            (``{model}_clean.dump``, ``{model}_anomalous.dump``).
        config:
            :class:`FilterConfig`; sensible defaults are used when omitted.
        reference_path:
            Path to a *clean* reference trajectory for IQR coordination
            calibration.  When *None* the input trajectory itself is used
            as its own reference (may produce over-wide thresholds for
            dirty trajectories).
        model_name:
            Label used to look up ``force_thresholds`` and as the output
            filename prefix.  Defaults to the input file stem.
        type_map:
            LAMMPS type-ID → atomic-number mapping (only relevant for
            LAMMPS dump inputs with non-atomic-number type IDs).
        input_format:
            One of ``"lammps-dump-text"`` or ``"extxyz"``.  Auto-detected
            from the file extension when omitted.

    Returns:
        :class:`FilterResult` with statistics and output paths.
    """
    if config is None:
        config = FilterConfig()

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not model_name:
        model_name = input_path.stem

    # Detect format
    fmt = input_format
    if fmt is None:
        suf = input_path.suffix.lower()
        if suf in (".dump", ".lammpstrj"):
            fmt = "lammps-dump-text"
        elif suf in (".xyz", ".extxyz"):
            fmt = "extxyz"
        else:
            raise ValueError(f"cannot detect format for {input_path.name}; use input_format=")

    # Read
    if fmt == "lammps-dump-text":
        frames = read_lammps_dump(input_path, type_map=type_map)
    elif fmt == "extxyz":
        frames = read_extxyz(input_path)
    else:
        raise ValueError(f"unsupported input format: {fmt}")

    if not frames:
        raise ValueError(f"no frames found in {input_path}")

    # Reference for coordination thresholds
    if reference_path is not None:
        ref_fmt = input_format
        if ref_fmt is None:
            rsuf = reference_path.suffix.lower()
            if rsuf in (".dump", ".lammpstrj"):
                ref_fmt = "lammps-dump-text"
            elif rsuf in (".xyz", ".extxyz"):
                ref_fmt = "extxyz"
        if ref_fmt == "lammps-dump-text":
            ref_frames = read_lammps_dump(reference_path, type_map=type_map)
        else:
            ref_frames = read_extxyz(reference_path)
    else:
        ref_frames = frames

    thresholds = establish_thresholds(ref_frames, config) if "coordination" in config.dimensions else {}

    clean_path = output_dir / f"{model_name}_clean.dump"
    anom_path = output_dir / f"{model_name}_anomalous.dump"

    stats = classify_and_write(frames, thresholds, config, clean_path, anom_path, model_name)

    return FilterResult(
        total=stats["total"],
        clean=stats["clean"],
        anomalous=stats["anom"],
        reasons={k: v for k, v in stats.items() if k not in ("total", "clean", "anom", "min_dist", "max_force")},
        thresholds=thresholds,
        min_dist=float(stats["min_dist"]),
        max_force=float(stats["max_force"]),
        clean_path=clean_path,
        anomalous_path=anom_path,
    )
