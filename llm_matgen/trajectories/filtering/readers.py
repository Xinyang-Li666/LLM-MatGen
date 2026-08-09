"""Streaming ASE-backed readers for filter input trajectories."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from .models import FilterFrame


def detect_filter_format(path: Path, explicit: str | None = None) -> str:
    if explicit:
        return explicit.lower()
    name = path.name.lower()
    suffix = path.suffix.lower()
    if name == "xdatcar":
        return "vasp-xdatcar"
    if suffix in {".xyz", ".extxyz"}:
        return "extxyz"
    if suffix in {".dump", ".lammpstrj"}:
        return "lammps-dump-text"
    if suffix == ".traj":
        return "traj"
    raise ValueError(f"cannot detect trajectory format for {path.name!r}; use --input-format")


class FilterTrajectoryReader:
    """Yield validated :class:`FilterFrame` objects without loading all frames."""

    def __init__(
        self,
        path: Path,
        input_format: str | None = None,
        lammps_type_map: dict[int, int | str] | None = None,
        assume_type_is_z: bool = False,
    ) -> None:
        self.path = Path(path)
        self.format = detect_filter_format(self.path, input_format)
        self.lammps_type_map = lammps_type_map or {}
        self.assume_type_is_z = assume_type_is_z

    def _iter_atoms(self):
        from ase.io import iread

        kwargs: dict[str, object] = {}
        if self.format == "lammps-dump-text" and self.lammps_type_map:
            max_type = max(self.lammps_type_map)
            specorder: list[str] = []
            from ase.data import chemical_symbols

            for type_id in range(1, max_type + 1):
                value = self.lammps_type_map.get(type_id)
                if isinstance(value, int):
                    if not 1 <= value < len(chemical_symbols):
                        raise ValueError(f"invalid atomic number for LAMMPS type {type_id}")
                    specorder.append(chemical_symbols[value])
                elif value and str(value).isdigit():
                    atomic_number = int(str(value))
                    if not 1 <= atomic_number < len(chemical_symbols):
                        raise ValueError(f"invalid atomic number for LAMMPS type {type_id}")
                    specorder.append(chemical_symbols[atomic_number])
                elif value:
                    specorder.append(str(value))
                else:
                    raise ValueError(f"missing mapping for LAMMPS type {type_id}")
            kwargs["specorder"] = specorder
        elif self.format == "lammps-dump-text" and not self.assume_type_is_z and not self._has_element_column():
            raise ValueError(
                "LAMMPS type mapping is missing; provide TYPE=ELEMENT or "
                "--assume-type-is-z to use type IDs as atomic numbers"
            )
        if self.format == "lammps-dump-text":
            # ASE's generic read wrapper materializes all selected LAMMPS frames.
            # Use the underlying image iterator so large dumps stay streaming.
            from ase.io.lammpsrun import iread_lammps_dump_text

            with self.path.open("r", encoding="utf-8", errors="replace") as stream:
                yield from iread_lammps_dump_text(stream, index=slice(None), **kwargs)
            return
        yield from iread(self.path, index=":", format=self.format, **kwargs)

    def _has_element_column(self) -> bool:
        if self.format != "lammps-dump-text":
            return False
        with self.path.open("r", encoding="utf-8", errors="replace") as stream:
            for _ in range(10000):
                line = stream.readline()
                if not line:
                    break
                if line.startswith("ITEM: ATOMS"):
                    return "element" in line.split()[2:]
        return False

    @staticmethod
    def _metadata(atoms) -> dict[str, object]:
        metadata: dict[str, object] = {}
        for key, value in atoms.info.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                metadata[key] = value
        return metadata

    def iter_frames(self) -> Iterator[FilterFrame]:
        for index, atoms in enumerate(self._iter_atoms()):
            cell = atoms.cell.array.copy() if atoms.cell.rank else None
            pbc = atoms.pbc.astype(bool, copy=True)
            forces = None
            for key in ("forces", "force"):
                if key in atoms.arrays:
                    forces = atoms.arrays[key].copy()
                    break
            if forces is None and atoms.calc is not None:
                candidate = atoms.calc.results.get("forces")
                if candidate is not None:
                    forces = candidate.copy()
            metadata = self._metadata(atoms)
            timestep = metadata.get("timestep", metadata.get("step"))
            yield FilterFrame(
                atomic_numbers=atoms.get_atomic_numbers(),
                positions=atoms.get_positions(),
                cell=cell,
                pbc=pbc,
                forces=forces,
                source_index=index,
                timestep=timestep if isinstance(timestep, (int, float)) else None,
                metadata=metadata,
            )

    def count_frames(self) -> int:
        return sum(1 for _ in self.iter_frames())
