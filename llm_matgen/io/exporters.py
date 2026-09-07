"""Safe exporters with parser round-trip verification."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pydantic import BaseModel, Field
from pymatgen.core import Structure
from pymatgen.core.periodic_table import Element
from pymatgen.io.cif import CifWriter
from pymatgen.io.vasp import Poscar

from llm_matgen.generators.models import OutputFormat
from llm_matgen.io.readers import read_structure


class ExportOptions(BaseModel):
    formats: list[OutputFormat] = Field(default_factory=lambda: [OutputFormat.POSCAR])
    output_dir: Path = Path("./output")
    poscar_direct: bool = True
    lammps_atom_style: str = "charge"


@dataclass
class ExportArtifact:
    structure_id: str
    format: OutputFormat
    path: Path
    sha256: str
    n_atoms: int
    formula: str
    metadata: dict[str, object]


@dataclass
class ExportResult:
    artifacts: list[ExportArtifact]


class StructureExporter:
    def export_structure(
        self,
        structure: Structure,
        structure_id: str,
        options: ExportOptions,
    ) -> ExportResult:
        self._validate_structure_id(structure_id)
        output_dir = options.output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        artifacts: list[ExportArtifact] = []
        for fmt in dict.fromkeys(options.formats):
            path = self._next_path(output_dir, structure_id, fmt)
            metadata = self._write(structure, path, fmt, options)
            read_kwargs = {}
            if fmt is OutputFormat.LAMMPS_DATA:
                read_kwargs["lammps_element_map"] = {
                    int(key): value for key, value in metadata["type_map"].items()
                }
            restored = read_structure(path, fmt=fmt.value, **read_kwargs)
            if (
                restored.num_sites != structure.num_sites
                or restored.composition != structure.composition
            ):
                path.unlink(missing_ok=True)
                raise ValueError(f"{fmt.value} round-trip changed structure composition")
            data = path.read_bytes()
            artifacts.append(
                ExportArtifact(
                    structure_id=structure_id,
                    format=fmt,
                    path=path,
                    sha256=hashlib.sha256(data).hexdigest(),
                    n_atoms=restored.num_sites,
                    formula=restored.composition.reduced_formula,
                    metadata=metadata,
                )
            )
        return ExportResult(artifacts=artifacts)

    @staticmethod
    def _validate_structure_id(structure_id: str) -> None:
        if (
            not structure_id
            or ".." in structure_id
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", structure_id) is None
        ):
            raise ValueError("structure_id must be a safe relative filename")

    @staticmethod
    def _next_path(output_dir: Path, structure_id: str, fmt: OutputFormat) -> Path:
        extension = {
            OutputFormat.POSCAR: ".vasp",
            OutputFormat.CIF: ".cif",
            OutputFormat.LAMMPS_DATA: ".data",
        }[fmt]
        candidate = output_dir / f"{structure_id}{extension}"
        index = 1
        while candidate.exists():
            candidate = output_dir / f"{structure_id}-{index}{extension}"
            index += 1
        return candidate

    @staticmethod
    def _write(
        structure: Structure,
        path: Path,
        fmt: OutputFormat,
        options: ExportOptions,
    ) -> dict[str, object]:
        if fmt is OutputFormat.POSCAR:
            Poscar(structure, sort_structure=True).write_file(
                path,
                direct=options.poscar_direct,
            )
            return {}
        elif fmt is OutputFormat.CIF:
            CifWriter(structure).write_file(path)
            return {}
        if fmt is OutputFormat.LAMMPS_DATA:
            return StructureExporter._write_lammps_data(structure, path, options.lammps_atom_style)
        raise ValueError(f"format is not implemented by this exporter: {fmt.value}")

    @staticmethod
    def _write_lammps_data(
        structure: Structure,
        path: Path,
        atom_style: str,
    ) -> dict[str, object]:
        if atom_style not in {"charge", "atomic"}:
            raise ValueError(f"unsupported LAMMPS atom style: {atom_style}")
        lattice = np.asarray(structure.lattice.matrix, dtype=float)
        if not np.allclose(lattice, np.diag(np.diag(lattice)), atol=1e-8):
            raise ValueError("LAMMPS exporter currently requires an orthogonal lattice")
        lengths = np.diag(lattice)
        if np.any(lengths <= 0):
            raise ValueError("LAMMPS box lengths must be positive")

        symbols: list[str] = []
        for site in structure:
            if not site.is_ordered:
                raise ValueError("LAMMPS data export requires ordered site occupancies")
            symbol = site.specie.symbol
            if symbol not in symbols:
                symbols.append(symbol)
        symbols.sort()
        type_map = {str(index): symbol for index, symbol in enumerate(symbols, start=1)}
        reverse_map = {symbol: index for index, symbol in enumerate(symbols, start=1)}
        masses = {
            str(index): float(Element(symbol).atomic_mass)
            for index, symbol in enumerate(symbols, start=1)
        }
        frac_coords = np.mod(np.asarray(structure.frac_coords, dtype=float), 1.0)
        cart_coords = frac_coords @ lattice

        lines = [
            "LLM-MatGen structure export",
            "",
            f"{len(structure)} atoms",
            f"{len(symbols)} atom types",
            "",
            f"0.0 {lengths[0]:.12g} xlo xhi",
            f"0.0 {lengths[1]:.12g} ylo yhi",
            f"0.0 {lengths[2]:.12g} zlo zhi",
            "",
            "Masses",
            "",
        ]
        lines.extend(
            f"{index} {masses[str(index)]:.12g}"
            for index in range(1, len(symbols) + 1)
        )
        lines.extend(["", f"Atoms # {atom_style}", ""])
        for atom_id, (site, coords) in enumerate(zip(structure, cart_coords, strict=True), start=1):
            type_id = reverse_map[site.specie.symbol]
            x, y, z = (float(value) for value in coords)
            if atom_style == "charge":
                lines.append(f"{atom_id} {type_id} 0.0 {x:.12g} {y:.12g} {z:.12g}")
            else:
                lines.append(f"{atom_id} {type_id} {x:.12g} {y:.12g} {z:.12g}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {
            "atom_style": atom_style,
            "type_map": type_map,
            "masses": masses,
            "contains_force_field": False,
        }
