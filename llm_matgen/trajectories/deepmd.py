"""Streaming DeepMD frame reader."""

from __future__ import annotations

import glob
import os
from pathlib import Path

import numpy as np
from pymatgen.core import Lattice, Structure

from .models import TrajectoryFrame


class DeepMDFrameReader:
    def __init__(self, root: Path, type_map: list[str] | None = None):
        self.root = Path(root)
        self.type_map = type_map
        self.systems = sorted({Path(path).parent for path in self.root.rglob("type.raw")})
        if not self.systems:
            raise ValueError(f"no DeepMD system containing type.raw found in {self.root}")

    def _system_map(self, system: Path) -> tuple[np.ndarray, list[str]]:
        types = np.loadtxt(system / "type.raw", ndmin=1).astype(int)
        map_path = system / "type_map.raw"
        if map_path.is_file():
            names = map_path.read_text(encoding="utf-8").split()
        elif self.type_map is not None:
            names = self.type_map
        else:
            raise ValueError(f"{system}: missing type_map.raw; provide --type-map")
        if len(names) <= int(types.max()):
            raise ValueError(f"{system}: type map has too few elements")
        return types, names

    def _iter_system(self, system: Path, offset: int):
        types, names = self._system_map(system)
        for set_dir in sorted(system.glob("set.*")):
            box = np.load(set_dir / "box.npy").reshape(-1, 3, 3)
            coord = np.load(set_dir / "coord.npy").reshape(len(box), -1, 3)
            if len(coord) != len(box) or coord.shape[1] != len(types):
                raise ValueError(f"{system}/{set_dir.name}: box/coord/type shape mismatch")
            energy_path, virial_path = set_dir / "energy.npy", set_dir / "virial.npy"
            energies = np.load(energy_path).reshape(-1) if energy_path.is_file() else None
            virials = np.load(virial_path).reshape(-1, 9) if virial_path.is_file() else None
            real_path = set_dir / "real_atom_types.npy"
            real_types = np.load(real_path).reshape(len(box), -1) if real_path.is_file() else None
            for local in range(len(box)):
                frame_types = real_types[local] if real_types is not None else types
                species = [names[int(value)] for value in frame_types]
                structure = Structure(Lattice(box[local]), species, coord[local], coords_are_cartesian=True)
                metadata = {"system": str(system), "set": set_dir.name, "local_index": local}
                if energies is not None and local < len(energies):
                    metadata["energy"] = float(energies[local])
                if virials is not None and local < len(virials):
                    metadata["has_virial"] = True
                yield TrajectoryFrame(structure, offset + local, f"{system}/{set_dir.name}", metadata)
            offset += len(box)

    def iter_frames(self):
        offset = 0
        for system in self.systems:
            yield from self._iter_system(system, offset)
            offset += sum(len(np.load(path).reshape(-1, 3, 3)) for path in system.glob("set.*/box.npy"))

    def count_frames(self) -> int:
        return sum(1 for _ in self.iter_frames())
