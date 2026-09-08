"""Batch exporters for selected trajectory frames."""

from __future__ import annotations

import hashlib
from pathlib import Path

from llm_matgen.generators.models import OutputFormat
from llm_matgen.io import readers
from llm_matgen.io.exporters import ExportOptions, StructureExporter


class FrameSeriesExporter:
    def export(self, frames, output_dir: Path, formats: list[OutputFormat]):
        output_dir.mkdir(parents=True, exist_ok=True)
        artifacts = []
        writer = StructureExporter()
        for export_index, frame in enumerate(frames, start=1):
            for fmt in dict.fromkeys(formats):
                if fmt is OutputFormat.POSCAR:
                    path = output_dir / f"POSCAR.{export_index}"
                elif fmt is OutputFormat.CIF:
                    path = output_dir / f"structure.{export_index}.cif"
                else:
                    path = output_dir / f"structure.{export_index}.data"
                if path.exists():
                    raise FileExistsError(f"output already exists: {path}")
                metadata = writer._write(frame.structure, path, fmt, ExportOptions(formats=[fmt]))
                read_kwargs = {}
                if fmt is OutputFormat.LAMMPS_DATA:
                    read_kwargs["lammps_element_map"] = {
                        int(key): value for key, value in metadata["type_map"].items()
                    }
                restored = readers.read_structure(path, fmt=fmt.value, **read_kwargs)
                if restored.num_sites != frame.structure.num_sites or restored.composition != frame.structure.composition:
                    path.unlink(missing_ok=True)
                    raise ValueError(f"{fmt.value} round-trip changed frame {frame.source_index}")
                artifacts.append({
                    "source_index": frame.source_index,
                    "export_index": export_index,
                    "format": fmt.value,
                    "path": path,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "metadata": metadata,
                })
        return artifacts
