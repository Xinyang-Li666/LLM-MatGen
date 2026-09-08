"""Readers for ordinary multi-frame trajectories using ASE."""

from __future__ import annotations

from pathlib import Path

from .models import TrajectoryFrame


def detect_trajectory_format(path: Path, explicit: str | None = None) -> str:
    if explicit:
        return explicit.lower()
    name = path.name.lower()
    if name == "xdatcar":
        return "vasp-xdatcar"
    if path.suffix.lower() in {".xyz", ".extxyz"}:
        return "extxyz"
    if path.suffix.lower() in {".dump", ".lammpstrj"}:
        return "lammps-dump-text"
    raise ValueError(f"cannot detect trajectory format for {path.name!r}; use --input-format")


class ASETrajectoryReader:
    def __init__(self, path: Path, input_format: str | None = None, lammps_element_map: dict[int, str] | None = None):
        self.path = Path(path)
        self.format = detect_trajectory_format(self.path, input_format)
        self.lammps_element_map = lammps_element_map or {}

    def _iter_atoms(self):
        from ase.io import iread

        kwargs = {"format": self.format}
        if self.format == "lammps-dump-text" and self.lammps_element_map:
            max_type_id = max(self.lammps_element_map)
            kwargs["specorder"] = [
                self.lammps_element_map.get(type_id, "X")
                for type_id in range(1, max_type_id + 1)
            ]
        return iread(self.path, index=":", **kwargs)

    def iter_frames(self):
        from pymatgen.io.ase import AseAtomsAdaptor

        adaptor = AseAtomsAdaptor()
        for index, atoms in enumerate(self._iter_atoms()):
            if atoms.cell.volume <= 0:
                raise ValueError(f"frame {index} has no valid periodic cell")
            structure = adaptor.get_structure(atoms)
            metadata = {}
            for key, value in atoms.info.items():
                if isinstance(value, (str, int, float, bool)) or value is None:
                    metadata[key] = value
            yield TrajectoryFrame(structure, index, str(self.path), metadata)

    def count_frames(self) -> int:
        return sum(1 for _ in self._iter_atoms())
