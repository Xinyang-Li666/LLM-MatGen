"""Command-line entry point for LLM-MatGen."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

EXIT_SUCCESS = 0
EXIT_PARAMETER = 2
EXIT_PARTIAL = 3
EXIT_SYSTEM = 4

GENERATOR_NAMES = (
    "vacancy",
    "interstitial",
    "doping",
    "solid-solution",
    "surface",
    "grain-boundary",
    "interface",
    "stacking-fault",
    "dislocation",
)


def _add_leaf(subparsers, name: str, help_text: str) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(name, help=help_text)
    parser.set_defaults(_selected_parser=parser)
    return parser


def _triple_int(value: str) -> tuple[int, int, int]:
    try:
        result = tuple(int(item.strip()) for item in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected three comma-separated integers") from exc
    if len(result) != 3:
        raise argparse.ArgumentTypeError("expected three comma-separated integers")
    return result  # type: ignore[return-value]


def _triple_float(value: str) -> tuple[float, float, float]:
    try:
        result = tuple(float(item.strip()) for item in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected three comma-separated numbers") from exc
    if len(result) != 3:
        raise argparse.ArgumentTypeError("expected three comma-separated numbers")
    return result  # type: ignore[return-value]


def _pair_float(value: str) -> tuple[float, float]:
    try:
        result = tuple(float(item.strip()) for item in value.split(","))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected two comma-separated numbers") from exc
    if len(result) != 2:
        raise argparse.ArgumentTypeError("expected two comma-separated numbers")
    return result  # type: ignore[return-value]


def _fraction(value: str) -> float:
    try:
        return float(value[:-1]) / 100 if value.endswith("%") else float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a fraction or percentage such as 0.05 or 5%") from exc


def _add_common_generate_args(parser: argparse.ArgumentParser, *, binary: bool = False) -> None:
    if binary:
        parser.add_argument("--film", required=True)
        parser.add_argument("--substrate", required=True)
    else:
        parser.add_argument("--input", required=True)
    parser.add_argument(
        "--format",
        dest="formats",
        action="append",
        choices=("poscar", "cif", "lammps-data"),
    )
    parser.add_argument("--output-root", default="output")
    parser.add_argument("--max-structures", type=int, default=1000)
    parser.add_argument("--max-atoms", type=int, default=100_000)
    parser.add_argument(
        "--lammps-element",
        action="append",
        default=[],
        metavar="TYPE=ELEMENT",
        help="override LAMMPS type mapping; missing types default to atomic numbers",
    )
    parser.set_defaults(_handler=_run_generate)


def _configure_generators(generators) -> None:
    vacancy = _add_leaf(generators, "vacancy", "generate vacancy structures")
    _add_common_generate_args(vacancy)
    vacancy.add_argument("--target-element", action="append", required=True)
    vacancy_group = vacancy.add_mutually_exclusive_group(required=True)
    vacancy_group.add_argument("--count", dest="counts", action="append", type=int)
    vacancy_group.add_argument("--concentration", type=_fraction)
    vacancy.add_argument("--variants", dest="variants_per_count", type=int, default=1)
    vacancy.add_argument("--seed", type=int)

    interstitial = _add_leaf(generators, "interstitial", "generate interstitial structures")
    _add_common_generate_args(interstitial)
    interstitial.add_argument("--element", dest="elements", action="append", required=True)
    interstitial.add_argument("--count", dest="counts", action="append", type=int, required=True)
    interstitial.add_argument("--variants", dest="variants_per_count", type=int, default=1)
    interstitial.add_argument("--min-distance", type=float, default=0.8)
    interstitial.add_argument("--candidate-mode", choices=("voronoi", "random"), default="voronoi")
    interstitial.add_argument("--seed", type=int)

    doping = _add_leaf(generators, "doping", "generate substitutional doping structures")
    _add_common_generate_args(doping)
    doping.add_argument("--dopant-element", action="append", required=True)
    doping.add_argument("--target-element", action="append", required=True)
    doping.add_argument("--count", dest="counts", action="append", type=int, required=True)
    doping.add_argument("--variants", dest="variants_per_combination", type=int, default=1)
    doping.add_argument("--allow-repeated-dopant", action="store_true")
    doping.add_argument("--seed", type=int)

    solid = _add_leaf(generators, "solid-solution", "generate solid-solution structures")
    _add_common_generate_args(solid)
    solid.add_argument("--target-element", required=True)
    solid.add_argument("--substituent", action="append", required=True, metavar="ELEMENT=RATIO")
    solid.add_argument("--method", choices=("random", "sqs"), default="random")
    solid.add_argument("--variants", type=int, default=1)
    solid.add_argument("--sqs-iterations", type=int, default=50_000)
    solid.add_argument("--seed", type=int)

    surface = _add_leaf(generators, "surface", "generate surface slabs")
    _add_common_generate_args(surface)
    surface.add_argument("--miller", action="append", type=_triple_int, required=True)
    surface.add_argument("--slab-size", type=float, required=True)
    surface.add_argument("--vacuum-size", type=float, required=True)
    surface.add_argument("--no-center", action="store_true")
    surface.add_argument("--conventional", action="store_true")

    grain = _add_leaf(generators, "grain-boundary", "generate grain boundaries")
    _add_common_generate_args(grain)
    grain.add_argument("--rotation-axis", type=_triple_int, required=True)
    grain.add_argument("--angle", action="append", type=float, required=True)
    grain.add_argument("--plane", type=_triple_int)
    grain.add_argument("--expand-times", type=int, default=4)
    grain.add_argument("--vacuum-thickness", type=float, default=0)
    grain.add_argument("--ab-shift", type=_pair_float, default=(0.0, 0.0))

    interface = _add_leaf(generators, "interface", "generate coherent interfaces")
    _add_common_generate_args(interface, binary=True)
    interface.add_argument("--film-miller", action="append", type=_triple_int, required=True)
    interface.add_argument("--substrate-miller", action="append", type=_triple_int, required=True)
    interface.add_argument("--film-thickness", type=float, required=True)
    interface.add_argument("--substrate-thickness", type=float, required=True)
    interface.add_argument("--vacuum-thickness", type=float, required=True)
    interface.add_argument("--gap", type=float, required=True)
    interface.add_argument("--max-area", type=float, default=400)
    interface.add_argument("--max-area-ratio-tol", type=float, default=0.09)
    interface.add_argument("--max-length-tol", type=float, default=0.03)
    interface.add_argument("--max-angle-tol", type=float, default=0.01)

    fault = _add_leaf(generators, "stacking-fault", "generate stacking faults")
    _add_common_generate_args(fault)
    fault.add_argument("--plane", type=_triple_int, required=True)
    fault.add_argument("--slip-vector", type=_triple_float, required=True)
    fault.add_argument("--fault-position", type=float, default=0.5)
    fault.add_argument("--repetitions", type=_triple_int, default=(1, 1, 1))
    fault.add_argument("--vacuum-thickness", type=float, default=0)

    dislocation = _add_leaf(generators, "dislocation", "generate dislocation structures")
    _add_common_generate_args(dislocation)
    dislocation.add_argument("--line-direction", type=_triple_int, required=True)
    dislocation.add_argument("--burgers-vector", type=_triple_float, required=True)
    dislocation.add_argument("--slip-plane", type=_triple_int, required=True)
    dislocation.add_argument("--character", choices=("edge", "screw", "mixed"), required=True)
    dislocation.add_argument("--core-position", type=_pair_float, required=True)
    dislocation.add_argument("--radius", type=float, required=True)
    dislocation.add_argument("--poisson-ratio", type=float, required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llm-matgen",
        description="Generate crystal structures with lightweight checks and reproducible manifests.",
    )
    commands = parser.add_subparsers(dest="command")
    search = _add_leaf(commands, "search", "search Materials Project structures")
    search.add_argument("--element", dest="elements", action="append")
    search.add_argument("--chemsys")
    search.add_argument("--formula")
    search.add_argument("--material-id", dest="material_ids", action="append")
    search.add_argument("--n-elements", type=int)
    search.add_argument("--formation-energy-max", type=float)
    search.add_argument("--band-gap-min", type=float)
    search.add_argument("--band-gap-max", type=float)
    search.add_argument(
        "--structure-class",
        choices=("layered", "perovskite", "spinel", "rocksalt", "fluorite"),
    )
    search.add_argument("--limit", type=int, default=100)
    search.set_defaults(_handler=_run_search)

    download = _add_leaf(commands, "download", "download Materials Project structures")
    download.add_argument("material_ids", nargs="+")
    download.add_argument("--output-dir", default="downloads")
    download.set_defaults(_handler=_run_download)

    properties = _add_leaf(commands, "properties", "collect Materials Project properties")
    properties.add_argument("material_ids", nargs="+")
    properties.add_argument(
        "--property", dest="property_names", action="append", required=True,
        choices=("thermo", "electronic", "magnetism", "dielectric", "phonon", "elasticity"),
    )
    properties.set_defaults(_handler=_run_properties)

    substrates = _add_leaf(commands, "substrates", "query substrate references")
    substrates.add_argument("material_ids", nargs="+")
    substrates.set_defaults(_handler=_run_substrates)

    generate = _add_leaf(commands, "generate", "generate local crystal structures")
    generators = generate.add_subparsers(dest="generator")
    _configure_generators(generators)

    check = _add_leaf(commands, "check", "run lightweight structure checks")
    check.add_argument("paths", nargs="+")
    check.add_argument(
        "--lammps-element", action="append", default=[], metavar="TYPE=ELEMENT",
        help="override LAMMPS type mapping; missing types default to atomic numbers",
    )
    check.set_defaults(_handler=_run_check)

    export = _add_leaf(commands, "export", "convert structures to supported formats")
    export.add_argument("paths", nargs="+")
    export.add_argument(
        "--format", dest="formats", action="append",
        choices=("poscar", "cif", "lammps-data"),
    )
    export.add_argument("--output-root", default="output")
    export.add_argument(
        "--lammps-element", action="append", default=[], metavar="TYPE=ELEMENT",
        help="override LAMMPS type mapping; missing types default to atomic numbers",
    )
    export.set_defaults(_handler=_run_export)
    convert = _add_leaf(commands, "convert", "convert multi-frame datasets")
    convert_commands = convert.add_subparsers(dest="convert_command")
    deepmd = _add_leaf(convert_commands, "deepmd", "convert DeepMD datasets to structure files")
    deepmd.add_argument("input")
    deepmd.add_argument("--output-root", default="output")
    deepmd.add_argument("--format", dest="formats", action="append", choices=("poscar", "cif", "lammps-data"))
    deepmd.add_argument("--stride", type=int, default=1)
    deepmd.add_argument("--type-map", action="append", default=[])
    deepmd.set_defaults(_handler=_run_convert_deepmd)
    sample = _add_leaf(commands, "sample", "sample multi-frame trajectories")
    sample_commands = sample.add_subparsers(dest="sample_command")
    trajectory = _add_leaf(sample_commands, "trajectory", "sample XYZ, XDATCAR, or LAMMPS trajectories")
    trajectory.add_argument("input")
    trajectory.add_argument("--method", choices=("uniform", "random"), required=True)
    trajectory.add_argument("--count", type=int, required=True)
    trajectory.add_argument("--seed", type=int)
    trajectory.add_argument("--input-format", choices=("extxyz", "vasp-xdatcar", "lammps-dump-text"))
    trajectory.add_argument("--format", dest="formats", action="append", choices=("poscar", "cif", "lammps-data"))
    trajectory.add_argument("--output-root", default="output")
    trajectory.add_argument("--lammps-element", action="append", default=[], metavar="TYPE=ELEMENT")
    trajectory.set_defaults(_handler=_run_sample_trajectory)
    representative = _add_leaf(sample_commands, "representative", "select representative trajectory frames with RDF/SOAP FPS")
    representative.add_argument("input", nargs="?")
    representative.add_argument("--source-config")
    representative.add_argument("--method", choices=("rdf-fps", "soap-fps"), required=True)
    representative.add_argument("--count", type=int, required=True)
    representative.add_argument("--allocation", choices=("proportional", "global"), default="proportional")
    representative.add_argument("--min-distance", type=float, default=0.0)
    representative.add_argument("--input-format", choices=("extxyz", "lammps-dump-text", "vasp-xdatcar"))
    representative.add_argument("--output-root", default="output")
    representative.add_argument("--cache-dir")
    representative.add_argument("--r-min", type=float, default=0.8)
    representative.add_argument("--r-max", type=float, default=6.0)
    representative.add_argument("--rdf-bin-width", type=float, default=0.05)
    representative.set_defaults(_handler=_run_sample_representative)
    # filter
    filt = _add_leaf(commands, "filter", "filter multi-frame trajectory data")
    filt_commands = filt.add_subparsers(dest="filter_command")
    filt_traj = _add_leaf(filt_commands, "trajectory", "filter non-physical frames from an MD trajectory")
    filt_traj.add_argument("input")
    filt_traj.add_argument("--reference")
    filt_traj.add_argument("--dimensions", nargs="+", default=None,
                           choices=("overlap", "force", "coordination"))
    filt_traj.add_argument("--checks", nargs="+", default=None,
                           choices=("overlap", "force", "coordination", "cell", "continuity"))
    filt_traj.add_argument("--output-root", default="output")
    filt_traj.add_argument("--model-name", default="")
    filt_traj.add_argument("--force-threshold", dest="force_thresholds", action="append", default=[],
                           metavar="MODEL=VALUE",
                           help="force ceiling per model, e.g. DPA-4=18.0")
    filt_traj.add_argument("--force-max", type=float)
    filt_traj.add_argument("--overlap-ratio", type=float, default=0.01)
    filt_traj.add_argument("--overlap-scale", type=float, default=0.55)
    filt_traj.add_argument("--overlap-floor", type=float, default=0.55)
    filt_traj.add_argument("--coord-cutoff", type=float, default=3.5)
    filt_traj.add_argument("--coord-group", dest="coord_groups_raw", action="append", default=[],
                           metavar="LABEL=Z1,Z2,...",
                           help="atomic-number groups for coordination averaging, e.g. cation=22,40,72")
    filt_traj.add_argument("--n-iqr", type=float, default=3.0)
    filt_traj.add_argument("--threshold-profile")
    filt_traj.add_argument("--output-format", choices=("extxyz", "lammps-dump"), default="extxyz")
    filt_traj.add_argument("--sample-count", type=int, default=300)
    filt_traj.add_argument("--sample-method", choices=("uniform", "random"), default="uniform")
    filt_traj.add_argument("--seed", type=int)
    filt_traj.add_argument("--strict", action="store_true")
    filt_traj.add_argument("--fail-on-anomaly", action="store_true")
    filt_traj.add_argument("--allow-variable-composition", action="store_true")
    filt_traj.add_argument("--assume-type-is-z", action="store_true")
    filt_traj.add_argument("--input-format", choices=("lammps-dump-text", "extxyz", "vasp-xdatcar", "traj"))
    filt_traj.add_argument("--lammps-element", action="append", default=[],
                           metavar="TYPE=ELEMENT",
                           help="map LAMMPS type IDs to atomic numbers")
    filt_traj.set_defaults(_handler=_run_filter_trajectory)

    db = _add_leaf(commands, "db", "manage local cache snapshots")
    db_commands = db.add_subparsers(dest="db_command")
    db_import = _add_leaf(db_commands, "import", "import snapshot archive")
    db_import.add_argument("path"); db_import.add_argument("--database", default="matgen.db")
    db_import.set_defaults(_handler=_run_db_import)
    db_export = _add_leaf(db_commands, "export", "export snapshot archive")
    db_export.add_argument("path"); db_export.add_argument("--database", default="matgen.db")
    db_export.set_defaults(_handler=_run_db_export)
    db_query = _add_leaf(db_commands, "query", "query cached snapshots")
    db_query.add_argument("--database", default="matgen.db"); db_query.add_argument("--element", dest="elements", action="append")
    db_query.add_argument("--formula-pattern"); db_query.add_argument("--n-elements", type=int); db_query.add_argument("--limit", type=int, default=100); db_query.add_argument("--all-snapshots", action="store_true")
    db_query.set_defaults(_handler=_run_db_query)
    db_list = _add_leaf(db_commands, "list", "list cached snapshots")
    db_list.add_argument("--database", default="matgen.db"); db_list.set_defaults(_handler=_run_db_query, elements=None, formula_pattern=None, n_elements=None, limit=100, all_snapshots=True)
    db_stats = _add_leaf(db_commands, "stats", "show cache statistics")
    db_stats.add_argument("--database", default="matgen.db"); db_stats.set_defaults(_handler=_run_db_stats)
    mcp = _add_leaf(commands, "mcp", "run the Model Context Protocol server")
    mcp.add_argument("--output-root", default="output")
    mcp.set_defaults(_handler=_run_mcp)
    config = _add_leaf(commands, "config", "manage non-sensitive configuration")
    config_commands = config.add_subparsers(dest="config_command")
    set_provider = _add_leaf(config_commands, "set-provider", "set the default provider")
    set_provider.add_argument("value")
    set_provider.set_defaults(_handler=_run_config_set, _config_field="provider")
    set_model = _add_leaf(config_commands, "set-model", "set the default model")
    set_model.add_argument("value")
    set_model.set_defaults(_handler=_run_config_set, _config_field="model")
    show = _add_leaf(config_commands, "show", "show redacted configuration")
    show.set_defaults(_handler=_run_config_show)
    set_key = _add_leaf(config_commands, "set-key", "explain secure credential configuration")
    set_key.add_argument("value")
    set_key.set_defaults(_handler=_run_config_set_key)
    return parser


def _run_mcp(args: argparse.Namespace) -> int:
    try:
        from llm_matgen.orchestration.tools import default_tool_registry
    except ImportError as exc:
        raise ValueError('MCP support is unavailable; install with `pip install "llm-matgen[mcp]"`') from exc
    from llm_matgen.mcp.server import MCPServer, serve_stdio
    registry = default_tool_registry(output_root=Path(args.output_root))
    serve_stdio(MCPServer(registry, args.output_root))
    return EXIT_SUCCESS


def _parse_substituents(values: list[str]) -> dict[str, float]:
    result: dict[str, float] = {}
    for value in values:
        try:
            element, ratio = value.split("=", 1)
            result[element.strip()] = _fraction(ratio.strip())
        except (ValueError, argparse.ArgumentTypeError) as exc:
            raise ValueError(f"invalid substituent {value!r}; expected ELEMENT=RATIO") from exc
    return result


def _parse_lammps_map(values: list[str]) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for value in values:
        try:
            type_id, element = value.split("=", 1)
            mapping[int(type_id)] = element.strip()
        except ValueError as exc:
            raise ValueError(f"invalid LAMMPS mapping {value!r}; expected TYPE=ELEMENT") from exc
    return mapping


def build_generation_request(args: argparse.Namespace):
    from llm_matgen.generators.models import OutputFormat
    from llm_matgen.io.exporters import ExportOptions
    from llm_matgen.services.generation import ExecutionLimits, GenerationRequest

    name = args.generator
    if name == "vacancy":
        parameters = {
            "target_elements": args.target_element,
            "counts": args.counts,
            "concentration": args.concentration,
            "variants_per_count": args.variants_per_count,
            "seed": args.seed,
        }
    elif name == "interstitial":
        parameters = {
            "elements": args.elements, "counts": args.counts,
            "variants_per_count": args.variants_per_count,
            "min_distance": args.min_distance, "candidate_mode": args.candidate_mode,
            "seed": args.seed,
        }
    elif name == "doping":
        parameters = {
            "dopant_elements": args.dopant_element,
            "target_elements": args.target_element,
            "dopant_counts": args.counts,
            "variants_per_combination": args.variants_per_combination,
            "allow_repeated_dopant": args.allow_repeated_dopant,
            "seed": args.seed,
        }
    elif name == "solid-solution":
        parameters = {
            "target_element": args.target_element,
            "substituents": _parse_substituents(args.substituent),
            "method": args.method, "variants": args.variants,
            "sqs_iterations": args.sqs_iterations, "seed": args.seed,
        }
    elif name == "surface":
        parameters = {
            "miller_indices": args.miller, "min_slab_size": args.slab_size,
            "min_vacuum_size": args.vacuum_size, "center_slab": not args.no_center,
            "primitive": not args.conventional,
        }
    elif name == "grain-boundary":
        parameters = {
            "rotation_axis": args.rotation_axis, "rotation_angles": args.angle,
            "plane": args.plane, "expand_times": args.expand_times,
            "vacuum_thickness": args.vacuum_thickness, "ab_shift": args.ab_shift,
        }
    elif name == "interface":
        parameters = {
            "film_millers": args.film_miller, "substrate_millers": args.substrate_miller,
            "film_thickness": args.film_thickness,
            "substrate_thickness": args.substrate_thickness,
            "vacuum_thickness": args.vacuum_thickness, "gap": args.gap,
            "max_area": args.max_area, "max_area_ratio_tol": args.max_area_ratio_tol,
            "max_length_tol": args.max_length_tol, "max_angle_tol": args.max_angle_tol,
        }
    elif name == "stacking-fault":
        parameters = {
            "plane": args.plane, "slip_vector": args.slip_vector,
            "fault_position": args.fault_position, "repetitions": args.repetitions,
            "vacuum_thickness": args.vacuum_thickness,
        }
    elif name == "dislocation":
        parameters = {
            "line_direction": args.line_direction, "burgers_vector": args.burgers_vector,
            "slip_plane": args.slip_plane, "character": args.character,
            "core_position": args.core_position, "radius": args.radius,
            "poisson_ratio": args.poisson_ratio,
        }
    else:
        raise ValueError(f"unknown generator: {name}")
    parameters = {key: value for key, value in parameters.items() if value is not None}
    root = Path.cwd().resolve()
    output_root = Path(args.output_root).resolve()
    if not output_root.is_relative_to(root):
        raise ValueError("output root must remain inside the current workspace")
    formats = [OutputFormat(value) for value in (args.formats or ["poscar"])]
    input_refs = [args.film, args.substrate] if name == "interface" else [args.input]
    request = GenerationRequest(
        generator=name,
        input_refs=input_refs,
        parameters=parameters,
        export_options=ExportOptions(formats=formats),
        limits=ExecutionLimits(
            max_structures=args.max_structures,
            max_atoms_per_structure=args.max_atoms,
            output_root=output_root,
        ),
    )
    request.__dict__["_lammps_element_map"] = _parse_lammps_map(args.lammps_element)
    return request


def _run_generate(args: argparse.Namespace) -> int:
    from llm_matgen.services.generation import GenerationService
    from llm_matgen.sources.local import LocalStructureSource

    request = build_generation_request(args)
    element_map = getattr(request, "_lammps_element_map", {})
    source = LocalStructureSource(
        allowed_roots=[Path.cwd()],
        lammps_element_map=element_map or None,
    )
    result = GenerationService(source=source).run(request)
    summary = {
        "ok": result.ok,
        "runs": [
            {
                "generated": run.generation.generated_count,
                "manifest": str(run.manifest_path),
                "errors": run.errors,
            }
            for run in result.runs
        ],
    }
    print(json.dumps(summary, ensure_ascii=False))
    return EXIT_SUCCESS if result.ok else EXIT_PARTIAL


def _safe_workspace_path(value: str) -> Path:
    root = Path.cwd().resolve()
    path = Path(value).resolve()
    if not path.is_relative_to(root):
        raise ValueError(f"path must remain inside the current workspace: {value}")
    return path


def _run_check(args: argparse.Namespace) -> int:
    from llm_matgen.checks.checker import LightStructureChecker
    from llm_matgen.generators.models import CheckLevel
    from llm_matgen.io import readers

    element_map = _parse_lammps_map(args.lammps_element)
    checker = LightStructureChecker()
    files = []
    contains_errors = False
    for value in args.paths:
        path = _safe_workspace_path(value)
        structure = readers.read_structure(
            path,
            lammps_element_map=element_map or None,
        )
        report = checker.check(structure)
        warning_count = sum(issue.level is CheckLevel.WARNING for issue in report.issues)
        error_count = sum(issue.level is CheckLevel.ERROR for issue in report.issues)
        contains_errors = contains_errors or error_count > 0
        files.append(
            {
                "path": str(path),
                "warnings": warning_count,
                "errors": error_count,
                "issues": [issue.model_dump(mode="json") for issue in report.issues],
            }
        )
    print(json.dumps({"files": files}, ensure_ascii=False))
    return EXIT_PARTIAL if contains_errors else EXIT_SUCCESS


def _run_export(args: argparse.Namespace) -> int:
    from datetime import datetime, timezone
    from uuid import uuid4

    from llm_matgen.checks.checker import LightStructureChecker
    from llm_matgen.generators.models import OutputFormat
    from llm_matgen.io import readers
    from llm_matgen.io.exporters import ExportOptions, StructureExporter
    from llm_matgen.io.manifest import (
        ManifestArtifact,
        ManifestStore,
        ManifestStructure,
        RunManifest,
    )
    from llm_matgen.utils.structure import structure_sha256

    root = Path.cwd().resolve()
    output_root = Path(args.output_root).resolve()
    if not output_root.is_relative_to(root):
        raise ValueError("output root must remain inside the current workspace")
    run_id = f"export-{uuid4().hex[:12]}"
    run_dir = output_root / run_id
    structures_dir = run_dir / "structures"
    structures_dir.mkdir(parents=True, exist_ok=False)
    formats = [OutputFormat(value) for value in (args.formats or ["poscar"])]
    element_map = _parse_lammps_map(args.lammps_element)
    exporter = StructureExporter()
    checker = LightStructureChecker()
    manifest_structures = []
    manifest_artifacts = []
    source_hashes = []
    failures = []
    for value in args.paths:
        path = _safe_workspace_path(value)
        structure = readers.read_structure(path, lammps_element_map=element_map or None)
        structure_id = structure_sha256(structure)
        source_hashes.append(structure_id)
        report = checker.check(structure)
        manifest_structures.append(
            ManifestStructure(
                structure_id=structure_id,
                parent_structure_id=structure_id,
                formula=structure.composition.reduced_formula,
                n_atoms=len(structure),
                actual_parameters={"source_path": str(path)},
                check_issues=[issue.model_dump(mode="json") for issue in report.issues],
            )
        )
        if not report.can_export:
            failures.append(f"{path}: lightweight check contains errors")
            continue
        exported = exporter.export_structure(
            structure,
            structure_id,
            ExportOptions(formats=formats, output_dir=structures_dir),
        )
        for artifact in exported.artifacts:
            manifest_artifacts.append(
                ManifestArtifact(
                    structure_id=structure_id,
                    format=artifact.format.value,
                    path=artifact.path.relative_to(run_dir).as_posix(),
                    sha256=artifact.sha256,
                    metadata=artifact.metadata,
                )
            )
    manifest = RunManifest(
        run_id=run_id,
        created_at=datetime.now(timezone.utc),
        software_version="0.1.0",
        input_source="local-export",
        parameters={"operation": "export", "source_hashes": source_hashes},
        structures=manifest_structures,
        artifacts=manifest_artifacts,
        warnings=failures,
    )
    manifest_path = ManifestStore(output_root).write_atomic(manifest, allow_existing_dir=True)
    print(
        json.dumps(
            {"ok": not failures, "manifest": str(manifest_path), "failures": failures},
            ensure_ascii=False,
        )
    )
    return EXIT_SUCCESS if not failures else EXIT_PARTIAL


def _trajectory_formats(values):
    from llm_matgen.generators.models import OutputFormat
    return [OutputFormat(value) for value in (values or ["poscar"])]


def _trajectory_output_root(value: str) -> Path:
    root = Path.cwd().resolve()
    output = Path(value).resolve()
    if not output.is_relative_to(root):
        raise ValueError("output root must remain inside the current workspace")
    return output


def _run_convert_deepmd(args: argparse.Namespace) -> int:
    from llm_matgen.trajectories.service import TrajectoryService

    input_dir = _safe_workspace_path(args.input)
    if args.stride <= 0:
        raise ValueError("stride must be positive")
    manifest = TrajectoryService().convert_deepmd(
        input_dir, _trajectory_output_root(args.output_root), _trajectory_formats(args.formats),
        stride=args.stride, type_map=args.type_map or None,
    )
    print(json.dumps({"ok": True, "manifest": str(manifest)}, ensure_ascii=False))
    return EXIT_SUCCESS


def _run_sample_trajectory(args: argparse.Namespace) -> int:
    from llm_matgen.trajectories.service import TrajectoryService

    manifest = TrajectoryService().sample_trajectory(
        _safe_workspace_path(args.input), _trajectory_output_root(args.output_root),
        args.method, args.count, seed=args.seed, input_format=args.input_format,
        formats=_trajectory_formats(args.formats), lammps_element_map=_parse_lammps_map(args.lammps_element),
    )
    print(json.dumps({"ok": True, "manifest": str(manifest)}, ensure_ascii=False))
    return EXIT_SUCCESS


def _run_sample_representative(args: argparse.Namespace) -> int:
    from llm_matgen.trajectories.filtering.readers import FilterTrajectoryReader
    from llm_matgen.trajectories.representative.engine import RepresentativeSamplingEngine
    from llm_matgen.trajectories.representative.models import RepresentativeSamplingRequest, SourceSpec
    from llm_matgen.trajectories.representative.rdf import RDFDescriptor, build_hybrid_channels
    from llm_matgen.trajectories.representative.sources import load_source_config

    if bool(args.input) == bool(args.source_config):
        raise ValueError("provide exactly one of INPUT or --source-config")
    if args.method == "soap-fps":
        raise ValueError("SOAP-FPS CLI requires the optional SOAP backend implemented in the next release stage")
    if args.source_config:
        specs = load_source_config(_safe_workspace_path(args.source_config))
    else:
        input_path = _safe_workspace_path(args.input)
        specs = (SourceSpec(input_path.stem, input_path, args.input_format or "extxyz"),)
    frames_by_source = {}
    all_elements = set()
    for spec in specs:
        frames = [item.frame for item in __import__("llm_matgen.trajectories.representative.sources", fromlist=["iter_source_frames"]).iter_source_frames(spec)]
        frames_by_source[spec.name] = frames
        for frame in frames:
            all_elements.update(int(value) for value in frame.atomic_numbers)
    descriptor = RDFDescriptor(
        build_hybrid_channels(tuple(sorted(all_elements))), args.r_min, args.r_max, args.rdf_bin_width
    )
    request = RepresentativeSamplingRequest(
        specs, args.method, args.count, allocation=args.allocation, min_distance=args.min_distance,
        output_root=_trajectory_output_root(args.output_root), cache_dir=(Path(args.cache_dir) if args.cache_dir else None),
    )
    result = RepresentativeSamplingEngine(request, descriptor).run(frames_by_source)
    print(json.dumps({"ok": True, "run_dir": str(result.run_dir), "selected_path": str(result.selected_path), "selected_count": result.selected_count}, ensure_ascii=False))
    return EXIT_SUCCESS


def _run_filter_trajectory(args: argparse.Namespace) -> int:
    from llm_matgen.trajectories.filtering.config import FilterConfig
    from llm_matgen.trajectories.filtering.engine import FilterEngine
    from llm_matgen.trajectories.filtering.profiles import ThresholdProfile
    from llm_matgen.trajectories.filtering.readers import FilterTrajectoryReader

    # Parse force thresholds: MODEL=VALUE
    force_map: dict[str, float] = {}
    for item in args.force_thresholds:
        try:
            model, val = item.split("=", 1)
            force_map[model.strip()] = float(val)
        except ValueError as exc:
            raise ValueError(f"invalid force threshold {item!r}; expected MODEL=VALUE") from exc

    # Parse coordination groups: LABEL=Z1,Z2,...
    coord_groups: dict[str, list[int]] = {}
    for item in args.coord_groups_raw:
        try:
            label, zlist = item.split("=", 1)
            coord_groups[label.strip()] = [int(z.strip()) for z in zlist.split(",")]
        except ValueError as exc:
            raise ValueError(f"invalid coord group {item!r}; expected LABEL=Z1,Z2,...") from exc

    checks = tuple(args.checks or args.dimensions or ["overlap"])
    model_name = args.model_name or Path(args.input).stem
    force_max = args.force_max if args.force_max is not None else force_map.get(model_name)
    config = FilterConfig(
        checks=checks,
        overlap_ratio=args.overlap_ratio,
        overlap_scale=args.overlap_scale,
        overlap_floor=args.overlap_floor,
        coord_cutoff=args.coord_cutoff,
        coord_groups=coord_groups if coord_groups else None,
        coord_iqr=args.n_iqr,
        force_max=force_max,
        sample_count=args.sample_count,
        sample_method=args.sample_method,
        seed=args.seed,
        allow_variable_composition=args.allow_variable_composition,
        strict=args.strict,
    )

    type_map = _parse_lammps_map(args.lammps_element)

    reference_path = _safe_workspace_path(args.reference) if args.reference else None

    input_path = _safe_workspace_path(args.input)
    reader_factory = lambda: FilterTrajectoryReader(
        input_path, args.input_format, type_map,
        assume_type_is_z=args.assume_type_is_z,
    ).iter_frames()
    reference_factory = None
    if reference_path is not None:
        reference_factory = lambda: FilterTrajectoryReader(
            reference_path, None, type_map,
            assume_type_is_z=args.assume_type_is_z,
        ).iter_frames()
    profile = None
    if args.threshold_profile:
        profile_path = _safe_workspace_path(args.threshold_profile)
        profile_data = json.loads(profile_path.read_text(encoding="utf-8"))
        profile = ThresholdProfile.from_dict(profile_data)
    result = FilterEngine(config, profile).run(
        reader_factory, _trajectory_output_root(args.output_root),
        reference_factory=reference_factory, output_format=args.output_format,
    )

    print(json.dumps({
        "ok": True,
        "total": result.total,
        "clean": result.clean,
        "anomalous": result.anomalous,
        "not_evaluated": list(result.not_evaluated),
        "anomalous_pct": round(100 * result.anomalous / max(result.total, 1), 1),
        "reasons": result.reasons,
        "run_dir": str(result.run_dir),
        "summary": str(result.summary_path),
        "clean_path": str(result.clean_path),
        "anomalous_path": str(result.anomalous_path),
    }, ensure_ascii=False))
    if args.fail_on_anomaly and result.anomalous:
        return EXIT_PARTIAL
    if args.strict and result.not_evaluated:
        return EXIT_PARTIAL
    return EXIT_SUCCESS


# Periodic table for element name → Z lookup
_ELEMENT_Z = {
    "H": 1, "He": 2, "Li": 3, "Be": 4, "B": 5, "C": 6, "N": 7, "O": 8, "F": 9, "Ne": 10,
    "Na": 11, "Mg": 12, "Al": 13, "Si": 14, "P": 15, "S": 16, "Cl": 17, "Ar": 18,
    "K": 19, "Ca": 20, "Sc": 21, "Ti": 22, "V": 23, "Cr": 24, "Mn": 25, "Fe": 26,
    "Co": 27, "Ni": 28, "Cu": 29, "Zn": 30, "Ga": 31, "Ge": 32, "As": 33, "Se": 34,
    "Br": 35, "Kr": 36, "Rb": 37, "Sr": 38, "Y": 39, "Zr": 40, "Nb": 41, "Mo": 42,
    "Tc": 43, "Ru": 44, "Rh": 45, "Pd": 46, "Ag": 47, "Cd": 48, "In": 49, "Sn": 50,
    "Sb": 51, "Te": 52, "I": 53, "Xe": 54, "Cs": 55, "Ba": 56, "La": 57, "Ce": 58,
    "Pr": 59, "Nd": 60, "Pm": 61, "Sm": 62, "Eu": 63, "Gd": 64, "Tb": 65, "Dy": 66,
    "Ho": 67, "Er": 68, "Tm": 69, "Yb": 70, "Lu": 71, "Hf": 72, "Ta": 73, "W": 74,
    "Re": 75, "Os": 76, "Ir": 77, "Pt": 78, "Au": 79, "Hg": 80, "Tl": 81, "Pb": 82,
    "Bi": 83, "Po": 84, "At": 85, "Rn": 86, "Fr": 87, "Ra": 88, "Ac": 89, "Th": 90,
    "Pa": 91, "U": 92, "Np": 93, "Pu": 94, "Am": 95, "Cm": 96,
}


def _run_config_set(args: argparse.Namespace) -> int:
    from llm_matgen.config import ConfigManager

    data = ConfigManager().set(args._config_field, args.value)
    print(json.dumps(data, ensure_ascii=False))
    return EXIT_SUCCESS


def _run_config_show(args: argparse.Namespace) -> int:
    from llm_matgen.config import ConfigManager

    print(json.dumps(ConfigManager().show(), ensure_ascii=False))
    return EXIT_SUCCESS


def _run_config_set_key(args: argparse.Namespace) -> int:
    raise ValueError(
        "credentials cannot be stored in the config file; use an environment variable or system keyring"
    )


def _run_search(args: argparse.Namespace) -> int:
    from llm_matgen.sources.mp import MPCollector, MaterialSearchQuery

    query = MaterialSearchQuery(
        elements=args.elements,
        chemsys=args.chemsys,
        formula=args.formula,
        material_ids=args.material_ids,
        n_elements=args.n_elements,
        formation_energy_max=args.formation_energy_max,
        band_gap_min=args.band_gap_min,
        band_gap_max=args.band_gap_max,
        structure_class=args.structure_class,
        limit=args.limit,
    )
    results = MPCollector().search(query)
    payload = []
    for item in results:
        classification = getattr(item, "classification", None)
        payload.append(
            {
                "material_id": item.material_id,
                "formula": getattr(item, "formula_pretty", None),
                "band_gap": getattr(item, "band_gap", None),
                "formation_energy_per_atom": getattr(item, "formation_energy_per_atom", None),
                "classification": (
                    classification.model_dump(mode="json")
                    if hasattr(classification, "model_dump")
                    else classification
                ),
            }
        )
    print(json.dumps({"results": payload}, ensure_ascii=False))
    return EXIT_SUCCESS


def _run_download(args: argparse.Namespace) -> int:
    from llm_matgen.sources.mp import MPCollector

    output_dir = _safe_workspace_path(args.output_dir)
    result = MPCollector().download(args.material_ids, output_dir)
    payload = {
        "successes": [
            {
                "material_id": item.source_reference,
                "path": str(item.local_path),
                "structure_hash": getattr(item, "structure_hash", None),
            }
            for item in result.successes
        ],
        "failures": [
            {
                "material_id": item.material_id,
                "error_type": item.error_type,
                "message": item.message,
            }
            for item in result.failures
        ],
    }
    print(json.dumps(payload, ensure_ascii=False))
    return EXIT_PARTIAL if result.failures else EXIT_SUCCESS


def _run_properties(args: argparse.Namespace) -> int:
    from llm_matgen.sources.mp import MPCollector

    results = MPCollector().fetch_properties(args.material_ids, args.property_names)
    materials = []
    for item in results:
        properties = {
            name: value.model_dump(mode="json") if hasattr(value, "model_dump") else value
            for name, value in item.properties.items()
        }
        materials.append({"material_id": item.material_id, "properties": properties})
    print(json.dumps({"materials": materials}, ensure_ascii=False))
    return EXIT_SUCCESS


def _run_substrates(args: argparse.Namespace) -> int:
    from llm_matgen.sources.mp import MPCollector

    results = MPCollector().search_substrates(args.material_ids)
    payload = [
        item.model_dump(mode="json") if hasattr(item, "model_dump") else item
        for item in results
    ]
    print(json.dumps({"results": payload}, ensure_ascii=False, default=str))
    return EXIT_SUCCESS

def _db_store(args):
    from llm_matgen.database import LocalStore
    return LocalStore(Path(args.database))

def _run_db_import(args):
    result = _db_store(args).import_json(Path(args.path))
    print(json.dumps({"inserted": result.inserted, "existing": result.existing, "failed": result.failed}, ensure_ascii=False)); return EXIT_SUCCESS

def _run_db_export(args):
    _db_store(args).export_json(Path(args.path)); print(json.dumps({"path": str(args.path)})); return EXIT_SUCCESS

def _run_db_query(args):
    from llm_matgen.database import LocalMaterialQuery
    results = _db_store(args).query(LocalMaterialQuery(elements=args.elements, formula_pattern=args.formula_pattern, n_elements=args.n_elements, limit=args.limit, all_snapshots=args.all_snapshots))
    print(json.dumps({"results": [s.model_dump(mode="json") for s in results]}, ensure_ascii=False)); return EXIT_SUCCESS

def _run_db_stats(args):
    store = _db_store(args)
    with store.connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM material_snapshots").fetchone()[0]
        materials = conn.execute("SELECT COUNT(DISTINCT material_id) FROM material_snapshots").fetchone()[0]
    print(json.dumps({"snapshots": count, "materials": materials})); return EXIT_SUCCESS


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "_handler", None)
    if handler is None:
        selected = getattr(args, "_selected_parser", parser)
        selected.print_help()
        return EXIT_SUCCESS
    try:
        return int(handler(args))
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_PARAMETER
    except Exception as exc:
        print(f"system error: {exc}", file=sys.stderr)
        return EXIT_SYSTEM


if __name__ == "__main__":
    raise SystemExit(main())
