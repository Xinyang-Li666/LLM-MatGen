"""Readers for the supported crystal structure formats."""

from __future__ import annotations

import re
import warnings
from pathlib import Path

from pymatgen.core import Lattice, Structure
from pymatgen.core.periodic_table import Element


class StructureReadError(ValueError):
    """Raised when a structure cannot be identified or parsed safely."""


def _detect_format(path: Path) -> str:
    if path.name.upper() == "POSCAR" or path.suffix.lower() in {".vasp", ".poscar"}:
        return "poscar"
    if path.suffix.lower() == ".cif":
        return "cif"
    if path.suffix.lower() in {".data", ".lammps"}:
        return "lammps-data"
    raise StructureReadError(f"cannot detect structure format for {path.name!r}")


def _read_lammps_data(
    path: Path,
    lammps_element_map: dict[int, str] | None,
) -> Structure:
    lines = path.read_text(encoding="utf-8").splitlines()
    atom_count = None
    bounds: dict[str, tuple[float, float]] = {}
    atom_section = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        atom_match = re.fullmatch(r"(\d+)\s+atoms", stripped)
        if atom_match:
            atom_count = int(atom_match.group(1))
        box_match = re.match(
            r"([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([xyz])lo\s+([xyz])hi",
            stripped,
        )
        if box_match:
            bounds[box_match.group(3)] = (
                float(box_match.group(1)),
                float(box_match.group(2)),
            )
        if stripped.lower().startswith("atoms"):
            atom_section = index

    if atom_count is None or len(bounds) != 3 or atom_section is None:
        raise StructureReadError("LAMMPS data is missing atoms or orthogonal box headers")
    atom_style = "charge"
    header = lines[atom_section].lower()
    if "#" in header:
        atom_style = header.split("#", 1)[1].strip().split()[0]
    if atom_style not in {"charge", "atomic"}:
        raise StructureReadError(f"unsupported LAMMPS atom style: {atom_style}")

    atoms: list[tuple[int, tuple[float, float, float]]] = []
    in_rows = False
    for line in lines[atom_section + 1 :]:
        stripped = line.strip()
        if not stripped:
            if in_rows and len(atoms) == atom_count:
                break
            continue
        if stripped[0].isalpha():
            if in_rows:
                break
            continue
        fields = stripped.split()
        if len(fields) < (6 if atom_style == "charge" else 5):
            if in_rows:
                break
            continue
        try:
            type_id = int(fields[1])
            coordinate_offset = 3 if atom_style == "charge" else 2
            coords = tuple(float(value) for value in fields[coordinate_offset : coordinate_offset + 3])
        except (TypeError, ValueError) as exc:
            raise StructureReadError("invalid LAMMPS atom row") from exc
        atoms.append((type_id, coords))
        in_rows = True
        if len(atoms) == atom_count:
            break

    if len(atoms) != atom_count:
        raise StructureReadError(f"expected {atom_count} LAMMPS atoms, read {len(atoms)}")

    lengths = [bounds[axis][1] - bounds[axis][0] for axis in "xyz"]
    if any(length <= 0 for length in lengths):
        raise StructureReadError("LAMMPS box lengths must be positive")
    origin = [bounds[axis][0] for axis in "xyz"]
    explicit_map = lammps_element_map or {}
    resolved_map: dict[int, str] = {}
    inferred: dict[int, str] = {}
    for type_id in sorted({item[0] for item in atoms}):
        if type_id in explicit_map:
            resolved_map[type_id] = explicit_map[type_id]
            continue
        try:
            symbol = Element.from_Z(type_id).symbol
        except (TypeError, ValueError) as exc:
            raise StructureReadError(
                f"LAMMPS type {type_id} is not a valid atomic number"
            ) from exc
        resolved_map[type_id] = symbol
        inferred[type_id] = symbol
    if inferred:
        mapping_text = ", ".join(f"{type_id}={symbol}" for type_id, symbol in inferred.items())
        warnings.warn(
            "LAMMPS element mapping is incomplete; inferred atomic-number mappings: "
            f"{mapping_text}. LAMMPS type IDs may be arbitrary; provide "
            "TYPE=ELEMENT mappings to override.",
            UserWarning,
            stacklevel=2,
        )
    species = [resolved_map[item[0]] for item in atoms]
    coords = [[value - origin[index] for index, value in enumerate(item[1])] for item in atoms]
    return Structure(Lattice.orthorhombic(*lengths), species, coords, coords_are_cartesian=True)


def read_structure(
    path: Path,
    fmt: str | None = None,
    *,
    lammps_element_map: dict[int, str] | None = None,
) -> Structure:
    path = Path(path)
    if not path.is_file():
        raise StructureReadError(f"structure file does not exist: {path}")
    selected = (fmt or _detect_format(path)).lower()
    try:
        if selected == "poscar":
            return Structure.from_file(path)
        if selected == "cif":
            return Structure.from_file(path)
        if selected == "lammps-data":
            return _read_lammps_data(path, lammps_element_map)
    except StructureReadError:
        raise
    except Exception as exc:
        raise StructureReadError(f"failed to parse {selected} structure: {path.name}") from exc
    raise StructureReadError(f"unsupported structure format: {selected}")
