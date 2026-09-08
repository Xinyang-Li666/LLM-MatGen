"""Natural language test harness for LLM-MatGen.

Connects an LLM provider (DeepSeek via OpenAI-compatible API) to the
LLM-MatGen tool registry with real handler implementations, then runs
natural-language prompts and records all interactions.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback

# Fix Windows GBK encoding issues
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

# ── project root ──────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from pymatgen.core import Structure

from llm_matgen.checks.checker import LightStructureChecker
from llm_matgen.generators import (
    DislocationGenerator, DislocationParams,
    DopingGenerator, DopingParams,
    GrainBoundaryGenerator, GrainBoundaryParams,
    InterfaceGenerator, InterfaceInput, InterfaceParams,
    InterstitialGenerator, InterstitialParams,
    SolidSolutionGenerator, SolidSolutionParams,
    StackingFaultGenerator, StackingFaultParams,
    SurfaceGenerator, SurfaceParams,
    VacancyGenerator, VacancyParams,
)
from llm_matgen.generators.models import GeneratedStructure, GenerationResult, OutputFormat
from llm_matgen.io.exporters import ExportOptions, StructureExporter
from llm_matgen.io.manifest import ManifestStore, RunManifest
from llm_matgen.io.readers import read_structure
from llm_matgen.orchestration.models import Message, ModelTurn, ToolResult
from llm_matgen.orchestration.runner import WorkflowRunner
from llm_matgen.orchestration.tools import ToolDefinition, ToolRegistry, _schema
from llm_matgen.sources.mp import (
    MPCollector, MaterialSearchQuery, MPDownloadResult, MPError,
)
from llm_matgen.utils.structure import structure_sha256

# ── paths ─────────────────────────────────────────────────────────
TEST_DIR = Path(__file__).resolve().parent
MP_DOWNLOAD_DIR = TEST_DIR / "mp-downloads"
OUTPUT_ROOT = TEST_DIR / "output"

# ── config ────────────────────────────────────────────────────────
MP_API_KEY = os.environ.get("MP_API_KEY")
LLM_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
LLM_BASE_URL = "https://api.deepseek.com"
LLM_MODEL = "deepseek-chat"


# ══════════════════════════════════════════════════════════════════════
# DeepSeek LLM Provider (OpenAI-compatible)
# ══════════════════════════════════════════════════════════════════════

class DeepSeekProvider:
    """OpenAI-compatible provider pointed at DeepSeek API."""

    def __init__(self, model: str = LLM_MODEL, api_key: str | None = LLM_API_KEY,
                 base_url: str = LLM_BASE_URL):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self._client = None

    def _get_client(self):
        if self._client is None:
            if not self.api_key:
                raise RuntimeError("DeepSeek API key is required; set DEEPSEEK_API_KEY")
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def complete(self, messages, tools):
        payload = [
            {"role": getattr(m, "role", "user"), "content": getattr(m, "content", "")}
            for m in messages
        ]
        tool_defs = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in tools
        ]
        try:
            response = self._get_client().chat.completions.create(
                model=self.model,
                messages=payload,
                tools=tool_defs or None,
                tool_choice="auto" if tool_defs else None,
            )
        except Exception as exc:
            raise RuntimeError(f"llm_api_error: {exc}") from exc

        msg = response.choices[0].message
        calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                calls.append(
                    ToolCall(
                        call_id=tc.id,
                        name=tc.function.name,
                        arguments=args,
                    )
                )

        from llm_matgen.orchestration.models import ToolCall as TCall
        return ModelTurn(
            text=msg.content,
            tool_calls=calls,
            finish_reason=response.choices[0].finish_reason or "stop",
        )


# ══════════════════════════════════════════════════════════════════════
# Tool handler state
# ══════════════════════════════════════════════════════════════════════

class ToolState:
    """Mutable state shared across tool handlers."""

    def __init__(self, mp_api_key: str | None = None):
        self.mp_collector = MPCollector(api_key=mp_api_key) if mp_api_key else None
        self.downloaded: dict[str, Path] = {}   # material_id → local CIF path
        self.search_cache: dict[str, list[dict]] = {}  # query key → results
        self.generated_count = 0


# ══════════════════════════════════════════════════════════════════════
# Tool handler implementations
# ══════════════════════════════════════════════════════════════════════

def _handle_search(state: ToolState, **kwargs) -> dict:
    """Search Materials Project with the given criteria."""
    query = MaterialSearchQuery(**kwargs)
    results = state.mp_collector.search(query)

    summary_items = []
    for item in results:
        entry = {
            "material_id": item.material_id,
            "formula": item.formula_pretty,
            "formation_energy_per_atom": item.formation_energy_per_atom,
            "band_gap": item.band_gap,
        }
        if item.classification is not None:
            entry["classification"] = {
                "label": item.classification.label,
                "matched": item.classification.matched,
                "score": item.classification.score,
            }
        summary_items.append(entry)

    return {
        "summary": f"found {len(results)} materials",
        "count": len(results),
        "results": summary_items,
    }


def _handle_download(state: ToolState, **kwargs) -> dict:
    """Download structures from Materials Project to local cache."""
    material_ids = kwargs.get("material_ids", [])
    if not material_ids:
        return {"ok": False, "summary": "no material_ids provided", "error_code": "invalid_arguments"}

    output_dir = MP_DOWNLOAD_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    result: MPDownloadResult = state.mp_collector.download(material_ids, output_dir)

    successes = []
    for s in result.successes:
        state.downloaded[s.source_reference] = s.local_path
        successes.append({
            "material_id": s.source_reference,
            "path": str(s.local_path),
            "structure_hash": s.structure_hash,
        })

    failures = [
        {"material_id": f.material_id, "error": f.error_type, "message": f.message}
        for f in result.failures
    ]

    return {
        "summary": f"downloaded {len(successes)}/{len(material_ids)} structures",
        "successes": successes,
        "failures": failures,
        "ok": len(failures) == 0,
    }


def _handle_properties(state: ToolState, **kwargs) -> dict:
    """Fetch material properties from Materials Project."""
    material_ids = kwargs.get("material_ids", [])
    property_names = kwargs.get("property_names", [])

    results = state.mp_collector.fetch_properties(material_ids, property_names)

    materials = []
    for item in results:
        props = {}
        for name, value in item.properties.items():
            if value.available:
                # Extract key numeric values for LLM consumption
                raw = value.value
                if hasattr(raw, 'bulk_modulus'):
                    props[name] = {
                        "bulk_modulus": getattr(raw, 'bulk_modulus', None),
                        "shear_modulus": getattr(raw, 'shear_modulus', None),
                        "available": True,
                    }
                elif hasattr(raw, 'band_gap'):
                    props[name] = {
                        "band_gap": getattr(raw, 'band_gap', None),
                        "available": True,
                    }
                else:
                    props[name] = {"available": True, "method": value.method}
            else:
                props[name] = {"available": False, "error": value.error}
        materials.append({"material_id": item.material_id, "properties": props})

    return {
        "summary": f"fetched properties for {len(materials)} materials",
        "materials": materials,
    }


def _handle_generate(state: ToolState, **kwargs) -> dict:
    """Generate defect structures."""
    generator_type = kwargs.get("generator", "")
    input_path = kwargs.get("input_path", "")
    parameters = kwargs.get("parameters", {})
    seed = kwargs.get("seed")
    export_formats = kwargs.get("export_formats", ["poscar"])
    output_dir_str = kwargs.get("output_dir", str(OUTPUT_ROOT))

    if seed is not None:
        parameters["seed"] = seed

    # Resolve input path
    input_p = Path(input_path)
    if not input_p.is_absolute():
        input_p = PROJECT_ROOT / input_p
    if not input_p.exists():
        return {"ok": False, "summary": f"input file not found: {input_path}", "error_code": "input_not_found"}

    try:
        structure = read_structure(input_p)
    except Exception as exc:
        return {"ok": False, "summary": f"failed to read input structure: {exc}", "error_code": "read_error"}

    # Set up output directory
    run_id = f"gen-{generator_type}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    output_dir = Path(output_dir_str) / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    structures_dir = output_dir / "structures"
    structures_dir.mkdir(parents=True, exist_ok=True)

    # Build generator registry
    registry = {
        "vacancy": (VacancyGenerator, VacancyParams),
        "interstitial": (InterstitialGenerator, InterstitialParams),
        "doping": (DopingGenerator, DopingParams),
        "solid-solution": (SolidSolutionGenerator, SolidSolutionParams),
        "surface": (SurfaceGenerator, SurfaceParams),
        "grain-boundary": (GrainBoundaryGenerator, GrainBoundaryParams),
        "interface": (InterfaceGenerator, InterfaceParams),
        "stacking-fault": (StackingFaultGenerator, StackingFaultParams),
        "dislocation": (DislocationGenerator, DislocationParams),
    }

    entry = registry.get(generator_type)
    if entry is None:
        return {"ok": False, "summary": f"unknown generator: {generator_type}", "error_code": "unknown_generator"}

    gen_cls, params_cls = entry

    # Validate and create params
    try:
        params = params_cls.model_validate(parameters)
    except Exception as exc:
        return {"ok": False, "summary": f"invalid parameters: {exc}", "error_code": "invalid_parameters"}

    # Create generator and run
    generator = gen_cls()
    result: GenerationResult = generator.generate(structure, params)

    # Run checker
    checker = LightStructureChecker()
    total_warnings = 0
    total_errors = 0

    for gs in result.generated:
        report = checker.check(gs.structure)
        total_warnings += sum(1 for i in report.issues if i.level.value == "warning")
        total_errors += sum(1 for i in report.issues if i.level.value == "error")

    # Export
    exporter = StructureExporter()
    formats = []
    for fmt_name in export_formats:
        try:
            fmt = OutputFormat(fmt_name.lower().replace("lammps-data", "lammps_data").replace("lammps_data", "lammps-data"))
        except ValueError:
            try:
                fmt = OutputFormat(fmt_name.lower().replace("-", "_"))
            except ValueError:
                continue
        formats.append(fmt)

    export_opts = ExportOptions(formats=formats, output_dir=structures_dir)
    exported_files: list[str] = []
    for gs in result.generated:
        exported = exporter.export_structure(gs.structure, gs.record.structure_id, export_opts)
        for art in exported.artifacts:
            exported_files.append(str(art.path))

    state.generated_count += result.generated_count

    return {
        "summary": f"generated {result.generated_count} {generator_type} structures",
        "generated_count": result.generated_count,
        "generator": generator_type,
        "formula": structure.composition.reduced_formula,
        "input_atoms": len(structure),
        "check_warnings": total_warnings,
        "check_errors": total_errors,
        "warnings": result.warnings,
        "exported_files": exported_files,
        "output_dir": str(output_dir),
        "parameters_used": params.model_dump(mode="json"),
    }


def _handle_check(state: ToolState, **kwargs) -> dict:
    """Run lightweight structure checks."""
    path_str = kwargs.get("path", "")
    input_p = Path(path_str)
    if not input_p.is_absolute():
        input_p = PROJECT_ROOT / input_p

    try:
        structure = read_structure(input_p)
    except Exception as exc:
        return {"ok": False, "summary": f"failed to read: {exc}", "error_code": "read_error"}

    checker = LightStructureChecker()
    report = checker.check(structure)

    issues = [
        {
            "level": issue.level.value,
            "category": issue.category,
            "message": issue.message,
        }
        for issue in report.issues
    ]

    return {
        "summary": f"check complete: {len([i for i in issues if i['level']=='error'])} errors, "
                   f"{len([i for i in issues if i['level']=='warning'])} warnings",
        "can_export": report.can_export,
        "issues": issues,
        "n_atoms": len(structure),
        "formula": structure.composition.reduced_formula,
    }


def _handle_export(state: ToolState, **kwargs) -> dict:
    """Export structure to specified formats."""
    path_str = kwargs.get("path", "")
    formats_str = kwargs.get("formats", ["poscar"])
    output_dir_str = kwargs.get("output_dir", str(OUTPUT_ROOT))

    input_p = Path(path_str)
    if not input_p.is_absolute():
        input_p = PROJECT_ROOT / input_p

    try:
        structure = read_structure(input_p)
    except Exception as exc:
        return {"ok": False, "summary": f"failed to read: {exc}", "error_code": "read_error"}

    structure_id = structure_sha256(structure)

    run_id = f"export-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    output_dir = Path(output_dir_str) / run_id / "structures"
    output_dir.mkdir(parents=True, exist_ok=True)

    formats = []
    for fmt_name in formats_str:
        try:
            formats.append(OutputFormat(fmt_name.lower()))
        except ValueError:
            continue

    exporter = StructureExporter()
    export_opts = ExportOptions(formats=formats, output_dir=output_dir)
    exported = exporter.export_structure(structure, structure_id, export_opts)

    files = [str(art.path) for art in exported.artifacts]
    return {
        "summary": f"exported to {len(files)} files",
        "files": files,
        "structure_hash": structure_id,
    }


def _handle_db_query(state: ToolState, **kwargs) -> dict:
    """Query local database snapshots."""
    return {
        "summary": "db_query: no local database configured for test harness",
        "results": [],
        "note": "Local DB not configured in test harness; use MP search instead.",
    }


# ══════════════════════════════════════════════════════════════════════
# Tool schemas
# ══════════════════════════════════════════════════════════════════════

SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "elements": {
            "type": "array", "items": {"type": "string"},
            "description": "Chemical elements that MUST be present, e.g. ['Li','Co','O']"
        },
        "chemsys": {
            "type": "string",
            "description": "Chemical system with elements separated by hyphens, e.g. 'Li-Co-O'. More precise than elements alone."
        },
        "formula": {
            "type": "string",
            "description": "Exact chemical formula to search, e.g. 'LiCoO2' or 'BaTiO3'"
        },
        "material_ids": {
            "type": "array", "items": {"type": "string"},
            "description": "Specific Materials Project material IDs, e.g. ['mp-19017']"
        },
        "n_elements": {
            "type": "integer",
            "description": "Exact number of elements in the material. Use to filter out complex compositions."
        },
        "formation_energy_max": {
            "type": "number",
            "description": "Maximum formation energy in eV/atom. Use negative values to find stable phases."
        },
        "band_gap_min": {
            "type": "number",
            "description": "Minimum band gap in eV. Use to find insulators/semiconductors."
        },
        "band_gap_max": {
            "type": "number",
            "description": "Maximum band gap in eV."
        },
        "structure_class": {
            "type": "string",
            "enum": ["layered", "perovskite", "spinel", "rocksalt", "fluorite"],
            "description": "Post-filter: downloads structures and classifies them. Only matched results are returned."
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of results to return (default 100, max 1000)."
        },
    },
    "additionalProperties": False,
}

DOWNLOAD_SCHEMA = {
    "type": "object",
    "properties": {
        "material_ids": {
            "type": "array", "items": {"type": "string"},
            "description": "List of Materials Project material IDs to download."
        },
    },
    "required": ["material_ids"],
    "additionalProperties": False,
}

PROPERTIES_SCHEMA = {
    "type": "object",
    "properties": {
        "material_ids": {
            "type": "array", "items": {"type": "string"},
            "description": "List of Materials Project material IDs."
        },
        "property_names": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": ["thermo", "electronic", "magnetism", "dielectric", "phonon", "elasticity"],
            },
            "description": "Property types: thermo (formation energy, etc.), electronic (band gap), magnetism (magnetic ordering), elasticity (bulk/shear modulus)."
        },
    },
    "required": ["material_ids", "property_names"],
    "additionalProperties": False,
}

GENERATE_SCHEMA = {
    "type": "object",
    "properties": {
        "generator": {
            "type": "string",
            "enum": [
            "vacancy", "interstitial", "doping", "solid-solution",
            "surface", "grain-boundary", "interface",
                "stacking-fault", "dislocation", "adsorption",
            ],
            "description": "Type of defect/structure generator to use."
        },
        "input_path": {
            "type": "string",
            "description": "Path to the input structure file (CIF or POSCAR). Use the path returned by download."
        },
        "parameters": {
            "type": "object",
            "description": (
                "Generator-specific parameters. Key parameters by generator:\n"
                "vacancy: target_elements (list[str]), concentration (float 0-1) OR counts (list[int]), variants_per_count (int)\n"
                "interstitial: elements (list[str]), counts (list[int]), min_distance (float, default 0.8), candidate_mode (str, default 'voronoi')\n"
                "doping: dopant_elements (list[str]), target_elements (list[str]), dopant_counts (list[int]), variants_per_combination (int), allow_repeated_dopant (bool)\n"
                "solid-solution: target_element (str), substituents (dict element→ratio, sum=1.0), variants (int), supercell (list[list[int]])\n"
                "surface: miller_indices (list[list[int]]), min_slab_size (float Å), min_vacuum_size (float Å), primitive (bool), "
                "cell_shape (native|near-orthogonal), orthogonal_max_area (int, default 8), "
                "orthogonal_tolerance (float degree, default 0.1); near-orthogonal means an approximate "
                "orthogonal/in-plane rectangular cell, not a guarantee that a≈b≈c; approximate cells "
                "may not be exportable as LAMMPS data\n"
                "grain-boundary: rotation_axis (list[int]), rotation_angles (list[float]), plane (list[int] optional), expand_times (int)\n"
                "interface: film_millers, substrate_millers (list[list[int]]), film_thickness, substrate_thickness, vacuum_thickness, gap (all float Å), max_area (float), max_area_ratio_tol, max_length_tol, max_angle_tol\n"
                "stacking-fault: plane (list[int]), slip_vector (list[float] fractional), fault_position (float 0-1), repetitions (list[int])\n"
                "dislocation: line_direction (list[int]), burgers_vector (list[float] Cartesian Å), slip_plane (list[int]), character (edge|screw|mixed), core_position (list[float]), radius (float Å), poisson_ratio (float)\n"
                "adsorption: slab path plus adsorbate path, anchor_index (one-based), reference_axis (list[float] for multi-atom rigid adsorbates), "
                "site_types, heights, azimuths, tilts, rolls, surface_side, history_policy (off|prefer|require), viewer (bool)\n"
            ),
        },
        "seed": {
            "type": "integer",
            "description": "Random seed for reproducibility."
        },
        "export_formats": {
            "type": "array",
            "items": {"type": "string", "enum": ["poscar", "cif", "lammps-data"]},
            "description": "Output formats. Default is ['poscar']. Use ['poscar', 'cif'] for both."
        },
        "output_dir": {
            "type": "string",
            "description": "Custom output directory. Defaults to tests/nl-tests/output/."
        },
    },
    "required": ["generator", "input_path", "parameters"],
    "additionalProperties": False,
}

CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Path to the structure file to check."
        },
    },
    "required": ["path"],
    "additionalProperties": False,
}

EXPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {
            "type": "string",
            "description": "Path to the structure file to export."
        },
        "formats": {
            "type": "array",
            "items": {"type": "string", "enum": ["poscar", "cif", "lammps-data"]},
            "description": "Output formats."
        },
        "output_dir": {
            "type": "string",
            "description": "Output directory."
        },
    },
    "required": ["path", "formats"],
    "additionalProperties": False,
}

DB_QUERY_SCHEMA = {
    "type": "object",
    "properties": {
        "elements": {"type": "array", "items": {"type": "string"}},
        "formula_pattern": {"type": "string"},
        "n_elements": {"type": "integer"},
        "limit": {"type": "integer"},
    },
    "additionalProperties": False,
}


# ══════════════════════════════════════════════════════════════════════
# Tool descriptions (critical for LLM understanding)
# ══════════════════════════════════════════════════════════════════════

TOOL_DESCRIPTIONS = {
    "search_materials": (
        "Search Materials Project for crystal structures matching given criteria. "
        "Use server-side filters (elements, chemsys, formula, n_elements, band_gap, formation_energy) "
        "for performance. Use structure_class as POST-filter (downloads + classifies; only returns matches). "
        "Always use tight constraints to avoid downloading hundreds of irrelevant structures. "
        "Returns list of matching material summaries with IDs, formulas, and properties."
    ),
    "download_structures": (
        "Download crystal structures from Materials Project by their material IDs. "
        "Saves CIF files locally. Returns local file paths for use in subsequent generate calls. "
        "Download multiple IDs at once when possible."
    ),
    "fetch_properties": (
        "Retrieve computed material properties from Materials Project. "
        "Use 'elasticity' for bulk/shear modulus (critical for dislocation mechanics). "
        "Use 'electronic' for band gap data. Use 'thermo' for formation energies. "
        "Returns structured property data keyed by material_id."
    ),
    "generate": (
        "Generate crystal defect structures from an input structure file. "
        "Select the appropriate generator and provide parameters based on the user's request. "
        "This is the CORE tool for creating defect structures. "
        "IMPORTANT: apply light structure checks automatically and report warning/error counts. "
        "Multiple independent operations on the same source structure should each be a separate generate call."
    ),
    "check": (
        "Run lightweight structure checks on a structure file. "
        "Checks format validity, lattice parameters, coordinate integrity, and close contacts. "
        "Returns issue list with warning/error classification."
    ),
    "export": (
        "Export a structure to specified file formats (POSCAR, CIF, LAMMPS data). "
        "Use when you need to convert an already-generated structure to additional formats."
    ),
    "db_query": (
        "Query the local structure cache database. "
        "Search by elements, formula pattern, or element count. "
        "Use when the user asks about previously cached or downloaded structures."
    ),
}


# ══════════════════════════════════════════════════════════════════════
# Build tool registry with real handlers
# ══════════════════════════════════════════════════════════════════════

def build_registry(state: ToolState) -> ToolRegistry:
    """Create a ToolRegistry with real handler implementations."""

    def _make_handler(fn):
        """Wrap handler to capture **kwargs and return ToolResult-compatible output."""
        def handler(**kwargs):
            try:
                result = fn(state, **kwargs)
                if isinstance(result, ToolResult):
                    return result
                return result  # dict → ToolExecutor wraps as ToolResult
            except MPError as exc:
                return {"ok": False, "summary": str(exc), "error_code": type(exc).__name__}
            except Exception as exc:
                traceback.print_exc()
                return {"ok": False, "summary": str(exc), "error_code": "handler_error"}
        return handler

    definitions = [
        ToolDefinition(
            name="search_materials",
            description=TOOL_DESCRIPTIONS["search_materials"],
            input_schema=SEARCH_SCHEMA,
            output_schema={"type": "object", "properties": {}, "additionalProperties": False},
            handler=_make_handler(_handle_search),
        ),
        ToolDefinition(
            name="download_structures",
            description=TOOL_DESCRIPTIONS["download_structures"],
            input_schema=DOWNLOAD_SCHEMA,
            output_schema={"type": "object", "properties": {}, "additionalProperties": False},
            handler=_make_handler(_handle_download),
            mutates_files=True,
        ),
        ToolDefinition(
            name="fetch_properties",
            description=TOOL_DESCRIPTIONS["fetch_properties"],
            input_schema=PROPERTIES_SCHEMA,
            output_schema={"type": "object", "properties": {}, "additionalProperties": False},
            handler=_make_handler(_handle_properties),
        ),
        ToolDefinition(
            name="generate",
            description=TOOL_DESCRIPTIONS["generate"],
            input_schema=GENERATE_SCHEMA,
            output_schema={"type": "object", "properties": {}, "additionalProperties": False},
            handler=_make_handler(_handle_generate),
            mutates_files=True,
        ),
        ToolDefinition(
            name="check",
            description=TOOL_DESCRIPTIONS["check"],
            input_schema=CHECK_SCHEMA,
            output_schema={"type": "object", "properties": {}, "additionalProperties": False},
            handler=_make_handler(_handle_check),
        ),
        ToolDefinition(
            name="export",
            description=TOOL_DESCRIPTIONS["export"],
            input_schema=EXPORT_SCHEMA,
            output_schema={"type": "object", "properties": {}, "additionalProperties": False},
            handler=_make_handler(_handle_export),
            mutates_files=True,
        ),
        ToolDefinition(
            name="db_query",
            description=TOOL_DESCRIPTIONS["db_query"],
            input_schema=DB_QUERY_SCHEMA,
            output_schema={"type": "object", "properties": {}, "additionalProperties": False},
            handler=_make_handler(_handle_db_query),
        ),
    ]
    return ToolRegistry(definitions)


# ══════════════════════════════════════════════════════════════════════
# Test execution
# ══════════════════════════════════════════════════════════════════════

# ── test prompts ───────────────────────────────────────────────────
# (loaded from the design doc, keyed by test ID)

TEST_PROMPTS = {
    "A1": """我需要为锂离子电池正极研究生成缺陷结构。请从 Materials Project 搜索
Li-Co-O 体系的层状氧化物（如 LiCoO₂ 及其衍生物），最多下载 5 个候选结构。
搜索时请同时使用 chemsys 和 structure_class 过滤，按形成能从低到高排序取前 5 个。

对下载的每个结构做两件事：
(1) 生成 Co 空位：浓度 5%，每种空位 2 个位点变体
(2) 对 Co 位进行 Ni 掺杂：替换 1 个和 2 个 Co 原子，每个掺杂方案 3 个变体

默认执行轻量检查，同时输出 POSCAR 和 CIF。种子设为 42。
最后总结生成了多少结构、有效结构数、几何检查警告数。""",
}


def run_test(test_id: str, provider, state: ToolState, registry: ToolRegistry,
             max_turns: int = 12) -> dict:
    """Run a single test and return full results."""
    prompt = TEST_PROMPTS.get(test_id)
    if prompt is None:
        raise ValueError(f"unknown test: {test_id}")

    runner = WorkflowRunner(
        provider=provider,
        registry=registry,
        max_turns=max_turns,
        max_tool_calls=64,
        max_generated_structures=5000,
    )

    print(f"\n{'='*70}")
    print(f"  Running {test_id}")
    print(f"{'='*70}")
    print(f"\n[PROMPT]\n{prompt}\n")

    start_time = time.monotonic()
    result = runner.ask(prompt)
    elapsed = time.monotonic() - start_time

    # Extract tool call log
    tool_log = []
    for tr in result.tool_results:
        tool_log.append({
            "call_id": tr.call_id,
            "ok": tr.ok,
            "summary": tr.summary,
            "error_code": tr.error_code,
            "structured_content": tr.structured_content,
        })

    final_text = result.text or "(no final text)"

    print(f"\n[RESULT] ok={result.ok}  turns={result.turns}  "
          f"tool_calls={result.tool_calls}  generated={result.generated_structures}  "
          f"elapsed={elapsed:.1f}s")
    print(f"\n[FINAL TEXT]\n{final_text}\n")

    if tool_log:
        print(f"[TOOL CALLS] ({len(tool_log)} total)")
        for i, tl in enumerate(tool_log):
            status = "✓" if tl["ok"] else "✗"
            print(f"  {i+1}. [{status}] {tl['summary'][:120]}")
            if tl.get("error_code"):
                print(f"      error: {tl['error_code']}")

    return {
        "test_id": test_id,
        "prompt": prompt,
        "ok": result.ok,
        "error_code": result.error_code,
        "turns": result.turns,
        "tool_calls": result.tool_calls,
        "generated_structures": result.generated_structures,
        "elapsed_seconds": round(elapsed, 1),
        "final_text": final_text,
        "tool_log": tool_log,
        "messages": [
            {"role": m.role, "content": m.content[:2000]}
            for m in result.messages
        ],
    }


# ══════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run NL tests for LLM-MatGen")
    parser.add_argument("test_id", help="Test ID to run, e.g. A1")
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--model", default=LLM_MODEL)
    parser.add_argument("--base-url", default=LLM_BASE_URL)
    parser.add_argument("--api-key", default=None, help="DeepSeek key; prefer DEEPSEEK_API_KEY")
    parser.add_argument("--mp-api-key", default=None, help="Materials Project key; prefer MP_API_KEY")
    parser.add_argument("--output", default=None, help="Save results to JSON file")
    args = parser.parse_args()

    # Ensure directories exist
    MP_DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    llm_api_key = args.api_key or os.environ.get("DEEPSEEK_API_KEY")
    mp_api_key = args.mp_api_key or os.environ.get("MP_API_KEY")
    if not llm_api_key:
        parser.error("missing DeepSeek key; set DEEPSEEK_API_KEY or pass --api-key")
    if not mp_api_key:
        parser.error("missing Materials Project key; set MP_API_KEY or pass --mp-api-key")

    # Build provider
    provider = DeepSeekProvider(
        model=args.model,
        api_key=llm_api_key,
        base_url=args.base_url,
    )

    # Build state and registry
    state = ToolState(mp_api_key=mp_api_key)
    registry = build_registry(state)

    # Run test
    result = run_test(
        args.test_id,
        provider,
        state,
        registry,
        max_turns=args.max_turns,
    )

    # Save results
    output_path = Path(args.output) if args.output else (
        TEST_DIR / f"{args.test_id}-result.json"
    )
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(f"\nResults saved to: {output_path}")

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
