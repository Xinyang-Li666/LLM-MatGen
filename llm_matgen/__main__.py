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
        help="element mapping needed when the input is LAMMPS data",
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
    check.add_argument("--lammps-element", action="append", default=[], metavar="TYPE=ELEMENT")
    check.set_defaults(_handler=_run_check)

    export = _add_leaf(commands, "export", "convert structures to supported formats")
    export.add_argument("paths", nargs="+")
    export.add_argument(
        "--format", dest="formats", action="append",
        choices=("poscar", "cif", "lammps-data"),
    )
    export.add_argument("--output-root", default="output")
    export.add_argument("--lammps-element", action="append", default=[], metavar="TYPE=ELEMENT")
    export.set_defaults(_handler=_run_export)
    _add_leaf(commands, "db", "manage local cache snapshots")
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
            "method": args.method, "variants": args.variants, "seed": args.seed,
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
