"""Safe streaming trajectory and report writers."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from ase import Atoms
from ase.calculators.lammps.coordinatetransform import Prism

from .models import FilterFrame


def frame_to_atoms(frame: FilterFrame) -> Atoms:
    atoms = Atoms(numbers=frame.atomic_numbers, positions=frame.positions, cell=frame.cell, pbc=frame.pbc)
    for key, value in frame.metadata.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            atoms.info[key] = value
    if frame.timestep is not None:
        atoms.info["timestep"] = frame.timestep
    if frame.forces is not None:
        from ase.calculators.singlepoint import SinglePointCalculator

        atoms.calc = SinglePointCalculator(atoms, forces=np.asarray(frame.forces, dtype=float))
    return atoms


class FilterWriters:
    def __init__(self, run_dir: Path, output_format: str = "extxyz") -> None:
        if output_format not in {"extxyz", "lammps-dump"}:
            raise ValueError("output_format must be extxyz or lammps-dump")
        self.run_dir = run_dir
        self.output_format = output_format
        self.clean_path = run_dir / f"clean.{ 'extxyz' if output_format == 'extxyz' else 'dump' }"
        self.anomalous_path = run_dir / f"anomalous.{ 'extxyz' if output_format == 'extxyz' else 'dump' }"
        self.review_path = run_dir / "frame-review.jsonl"
        self.clean_part = self.clean_path.with_name(self.clean_path.name + ".part")
        self.anomalous_part = self.anomalous_path.with_name(self.anomalous_path.name + ".part")
        self.review_part = self.review_path.with_name(self.review_path.name + ".part")
        self.clean_part.touch()
        self.anomalous_part.touch()
        self._written = {"clean": False, "anomalous": False}
        self._review = self.review_part.open("w", encoding="utf-8")

    def write_frame(self, frame: FilterFrame, anomalous: bool, review: dict[str, object]) -> None:
        from ase.io import write

        label = "anomalous" if anomalous else "clean"
        path = self.anomalous_part if anomalous else self.clean_part
        if self.output_format == "lammps-dump":
            self._write_lammps_frame(path, frame)
        else:
            write(path, frame_to_atoms(frame), format="extxyz", append=self._written[label])
        self._written[label] = True
        self._review.write(json.dumps(review, ensure_ascii=False, allow_nan=False) + "\n")

    @staticmethod
    def _write_lammps_frame(path: Path, frame: FilterFrame) -> None:
        if frame.cell is not None:
            prism = Prism(frame.cell)
            lx, ly, lz, xy, xz, yz = map(float, prism.get_lammps_prism())
            positions = prism.vector_to_lammps(frame.positions, wrap=False)
            bounds = [(0.0, lx, xy), (0.0, ly, xz), (0.0, lz, yz)]
        else:
            low = np.min(frame.positions, axis=0) - 1.0
            high = np.max(frame.positions, axis=0) + 1.0
            positions = frame.positions
            bounds = [(float(low[i]), float(high[i]), 0.0) for i in range(3)]
        periodic_labels = ["p" if bool(value) else "f" for value in frame.pbc]
        with path.open("a", encoding="utf-8") as stream:
            stream.write("ITEM: TIMESTEP\n")
            stream.write(f"{frame.timestep if frame.timestep is not None else frame.source_index}\n")
            stream.write("ITEM: NUMBER OF ATOMS\n")
            stream.write(f"{frame.natoms}\n")
            stream.write("ITEM: BOX BOUNDS xy xz yz " + " ".join(periodic_labels) + "\n")
            for lo, hi, tilt in bounds:
                stream.write(f"{lo:.16e} {hi:.16e} {tilt:.16e}\n")
            columns = "id type x y z"
            if frame.forces is not None:
                columns += " fx fy fz"
            stream.write(f"ITEM: ATOMS {columns}\n")
            for index, (atomic_number, position) in enumerate(zip(frame.atomic_numbers, positions), start=1):
                values = f"{index} {int(atomic_number)} {position[0]:.16e} {position[1]:.16e} {position[2]:.16e}"
                if frame.forces is not None:
                    force = frame.forces[index - 1]
                    values += f" {force[0]:.16e} {force[1]:.16e} {force[2]:.16e}"
                stream.write(values + "\n")

    def close(self, success: bool = True) -> None:
        self._review.close()
        if success:
            self.clean_part.replace(self.clean_path)
            self.anomalous_part.replace(self.anomalous_path)
            self.review_part.replace(self.review_path)
