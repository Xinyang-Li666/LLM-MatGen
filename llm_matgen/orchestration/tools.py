"""Deterministic tool definitions and safe execution facade."""
from __future__ import annotations
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, ValidationError

from .models import ToolResult

class ToolError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message); self.code = code

def _schema(model_or_schema: Any) -> dict[str, Any]:
    if model_or_schema is None: return {"type":"object", "properties":{}, "additionalProperties":False}
    if isinstance(model_or_schema, dict):
        out = dict(model_or_schema)
    elif isinstance(model_or_schema, type) and issubclass(model_or_schema, BaseModel):
        out = model_or_schema.model_json_schema()
    else: out = {"type":"object", "properties":{}}
    out.setdefault("type", "object")
    def seal(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node: node["additionalProperties"] = False
            for value in node.values(): seal(value)
        elif isinstance(node, list):
            for value in node: seal(value)
    seal(out)
    out["additionalProperties"] = False
    # Keep nested object schemas closed as well; this prevents provider-side
    # argument smuggling when a Pydantic model contains dictionaries/models.
    def close(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object": node["additionalProperties"] = False
            for value in node.values(): close(value)
        elif isinstance(node, list):
            for value in node: close(value)
    close(out)
    return out

@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    handler: Callable[..., Any]
    mutates_files: bool = False

    def __post_init__(self):
        if not self.name or not self.description: raise ValueError("tool name and description are required")
        if not callable(self.handler): raise TypeError("handler must be callable")
        object.__setattr__(self, "input_schema", _schema(self.input_schema))
        object.__setattr__(self, "output_schema", _schema(self.output_schema))
        props = set(self.input_schema.get("properties", {}))
        params = inspect.signature(self.handler).parameters
        if props and not any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
            accepted = {p.name for p in params.values() if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)}
            if not props.issubset(accepted):
                raise ValueError(f"tool schema parameters do not match handler signature: {sorted(props - accepted)}")

class ToolRegistry:
    def __init__(self, definitions: list[ToolDefinition] | None = None):
        self._items: dict[str, ToolDefinition] = {}
        for item in definitions or []: self.register(item)
    def register(self, definition: ToolDefinition) -> ToolDefinition:
        if definition.name in self._items: raise ValueError(f"duplicate tool name: {definition.name}")
        self._items[definition.name] = definition; return definition
    def get(self, name: str) -> ToolDefinition | None: return self._items.get(name)
    def definitions(self) -> tuple[ToolDefinition, ...]: return tuple(self._items.values())
    def list_tools(self) -> tuple[ToolDefinition, ...]: return self.definitions()
    def execute(self, name: str, arguments: Mapping[str, Any] | None = None) -> ToolResult:
        return ToolExecutor(self).call(name, arguments or {})

class ToolExecutor:
    def __init__(self, registry: ToolRegistry): self.registry = registry
    def call(self, name: str, arguments: Mapping[str, Any] | None = None, call_id: str = "") -> ToolResult:
        tool = self.registry.get(name)
        if tool is None: return ToolResult(call_id=call_id, ok=False, summary=f"unknown tool: {name}", error_code="tool_not_found")
        args = dict(arguments or {})
        try:
            result = tool.handler(**args)
            if isinstance(result, ToolResult): return result.model_copy(update={"call_id": call_id or result.call_id})
            if isinstance(result, BaseModel): payload = result.model_dump(mode="json")
            elif isinstance(result, Mapping): payload = dict(result)
            else: payload = {"value": result}
            refs = payload.pop("artifact_refs", []) if isinstance(payload, dict) else []
            summary = payload.pop("summary", "tool completed") if isinstance(payload, dict) else "tool completed"
            return ToolResult(call_id=call_id, ok=True, summary=str(summary), structured_content=payload, artifact_refs=list(refs or []))
        except ValidationError as exc:
            return ToolResult(call_id=call_id, ok=False, summary="invalid tool arguments", error_code="invalid_arguments", structured_content={"details": json.loads(exc.json())})
        except ToolError as exc:
            return ToolResult(call_id=call_id, ok=False, summary=str(exc), error_code=exc.code)
        except TypeError as exc:
            return ToolResult(call_id=call_id, ok=False, summary=str(exc), error_code="invalid_arguments")
        except Exception as exc:
            return ToolResult(call_id=call_id, ok=False, summary=str(exc), error_code="handler_error")

def _placeholder(name: str):
    def handler(**kwargs): raise ToolError("not_configured", f"{name} tool requires an application context")
    return handler


class _ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GenerateAdsorptionArguments(_ToolArguments):
    slab: str
    adsorbate: str
    anchor_index: PositiveInt = 1
    reference_axis: tuple[float, float, float] | None = None
    site_types: tuple[str, ...] = ("top",)
    heights: tuple[float, ...] = (2.0,)
    azimuths: tuple[float, ...] = (0.0,)
    tilts: tuple[float, ...] = (0.0,)
    rolls: tuple[float, ...] = (0.0,)
    history_policy: Literal["off", "prefer", "require"] = "off"
    surface_side: Literal["top", "bottom", "both"] = "top"
    fixed_bottom_layers: int = Field(default=0, ge=0)
    layer_tolerance: float = Field(default=0.15, gt=0)
    max_structures: PositiveInt = Field(default=100, le=1000)
    max_attempts: PositiveInt | None = Field(default=None, le=1_000_000)
    max_atoms_per_structure: PositiveInt = Field(default=100_000, le=100_000)
    formats: tuple[Literal["poscar", "cif", "lammps-data"], ...] = ("poscar",)
    viewer: bool = True


class GenerateSurfaceArguments(_ToolArguments):
    structure: str
    miller_indices: tuple[tuple[int, int, int], ...]
    min_slab_size: float = Field(default=10.0, gt=0)
    min_vacuum_size: float = Field(default=15.0, gt=0)
    center_slab: bool = True
    primitive: bool = True
    cell_shape: Literal["native", "near-orthogonal"] = "near-orthogonal"
    orthogonal_max_area: PositiveInt = Field(default=8, le=100)
    orthogonal_tolerance: float = Field(default=0.1, gt=0)
    max_structures: PositiveInt = Field(default=100, le=1000)
    max_atoms_per_structure: PositiveInt = Field(default=100_000, le=100_000)
    formats: tuple[Literal["poscar", "cif", "lammps-data"], ...] = ("poscar",)
    viewer: bool = True


class CasesStatusArguments(_ToolArguments):
    pass


class CasesQueryArguments(_ToolArguments):
    top_k: PositiveInt = Field(default=10, le=1000)


class CasesInspectArguments(_ToolArguments):
    revision_id: str = Field(min_length=1, max_length=512)


class RevisionImportArguments(_ToolArguments):
    parent: str
    child: str
    sidecar: str


def _validate(model: type[_ToolArguments], values: Mapping[str, Any]) -> _ToolArguments:
    return model.model_validate(values)


def _artifact_uri(output_root: Path, path: Path) -> str:
    resolved = path.resolve()
    if not resolved.is_relative_to(output_root):
        raise ToolError("artifact_outside_output_root", "tool produced an artifact outside the output root")
    return f"artifact://{resolved.relative_to(output_root).as_posix()}"


def _safe_workspace_file(reference: str) -> Path:
    workspace = Path.cwd().resolve()
    path = Path(reference).resolve()
    if not path.is_relative_to(workspace):
        raise ToolError("path_denied", "input path is outside the current workspace")
    if not path.is_file():
        raise ToolError("not_found", f"input file does not exist: {reference}")
    return path


def default_tool_registry(output_root: Any = "output") -> ToolRegistry:
    resolved_output_root = Path(output_root).resolve()

    def run_generation(generator: str, input_refs: list[str], parameters: dict[str, Any], args):
        from llm_matgen.generators.models import OutputFormat
        from llm_matgen.io.exporters import ExportOptions
        from llm_matgen.services.generation import ExecutionLimits, GenerationRequest, GenerationService
        from llm_matgen.sources.local import LocalStructureSource

        request = GenerationRequest(
            generator=generator,
            input_refs=input_refs,
            parameters=parameters,
            export_options=ExportOptions(formats=[OutputFormat(value) for value in args.formats]),
            limits=ExecutionLimits(
                output_root=resolved_output_root,
                max_structures=args.max_structures,
                max_atoms_per_structure=args.max_atoms_per_structure,
            ),
            viewer=args.viewer,
        )
        return GenerationService(LocalStructureSource([Path.cwd()])).run(request)

    def generation_payload(result, label: str):
        manifests = [_artifact_uri(resolved_output_root, run.manifest_path) for run in result.runs]
        viewers = [
            _artifact_uri(resolved_output_root, run.viewer_path)
            for run in result.runs
            if run.viewer_path is not None
        ]
        candidates = [
            {
                "structure_id": item.record.structure_id,
                "formula": item.record.formula,
                "n_atoms": item.record.n_atoms,
                "metadata": item.record.actual_parameters,
            }
            for run in result.runs
            for item in run.generation.generated
        ]
        return {
            "summary": f"generated {len(candidates)} {label} structures",
            "ok": result.ok,
            "generated_count": len(candidates),
            "candidates": candidates,
            "manifests": manifests,
            "viewers": viewers,
            "artifact_refs": [*manifests, *viewers],
        }

    def generate_surface(**kwargs):
        args = _validate(GenerateSurfaceArguments, kwargs)
        structure = _safe_workspace_file(args.structure)
        parameters = args.model_dump(
            exclude={"structure", "formats", "viewer", "max_atoms_per_structure"},
            mode="json",
        )
        result = run_generation("surface", [str(structure)], parameters, args)
        return generation_payload(result, "surface")

    def generate_adsorption(**kwargs):
        args = _validate(GenerateAdsorptionArguments, kwargs)
        slab = _safe_workspace_file(args.slab)
        adsorbate = _safe_workspace_file(args.adsorbate)
        parameters = args.model_dump(
            exclude={"slab", "adsorbate", "formats", "viewer", "max_atoms_per_structure"},
            mode="json",
        )
        result = run_generation("adsorption", [str(slab), str(adsorbate)], parameters, args)
        return generation_payload(result, "adsorption")

    def case_store():
        from llm_matgen.adsorption.store import AdsorptionCaseStore
        from llm_matgen.config import ConfigManager

        return AdsorptionCaseStore(ConfigManager().load_adsorption().resolved_store_root)

    def cases_status(**kwargs):
        _validate(CasesStatusArguments, kwargs)
        store = case_store()
        status = store.status()
        status["active_revisions"] = len(store.list_revisions())
        return {"summary": "adsorption case store status", "status": status}

    def cases_query(**kwargs):
        args = _validate(CasesQueryArguments, kwargs)
        items = case_store().list_revisions()[:args.top_k]
        return {
            "summary": f"found {len(items)} adsorption case revisions",
            "matches": [
                {
                    "case_id": item.case_id,
                    "revision_id": item.revision_id,
                    "status": item.status.value,
                    "score": 1.0,
                    "index_revision": item.index_revision,
                }
                for item in items
            ],
        }

    def cases_inspect(**kwargs):
        args = _validate(CasesInspectArguments, kwargs)
        item = next(
            (entry for entry in case_store().list_revisions(include_superseded=True) if entry.revision_id == args.revision_id),
            None,
        )
        if item is None:
            raise ToolError("not_found", f"unknown case revision: {args.revision_id}")
        return {
            "summary": f"inspected adsorption case revision {item.revision_id}",
            "case": {
                "case_id": item.case_id,
                "revision_id": item.revision_id,
                "status": item.status.value,
                "artifact_relative_path": item.artifact_relative_path,
                "index_revision": item.index_revision,
                "superseded_by": item.superseded_by,
            },
        }

    def revision_import(**kwargs):
        from llm_matgen.adsorption.revision import RevisionImporter, RevisionSidecarV1, RevisionSidecarV2
        from llm_matgen.io.readers import read_structure

        args = _validate(RevisionImportArguments, kwargs)
        parent = _safe_workspace_file(args.parent)
        child = _safe_workspace_file(args.child)
        sidecar = _safe_workspace_file(args.sidecar)
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        model = RevisionSidecarV1 if int(payload.get("version", 1)) == 1 else RevisionSidecarV2
        imported = RevisionImporter(resolved_output_root / "revisions").import_revision(
            read_structure(parent), read_structure(child), model.model_validate(payload)
        )
        manifest = imported.path / "manifest.json"
        artifact_ref = _artifact_uri(resolved_output_root, manifest)
        return {
            "summary": "imported one audited structure revision",
            "version": 2,
            "path": str(imported.path),
            "parent_hash": imported.parent_hash,
            "child_hash": imported.child_hash,
            "artifact_refs": [artifact_ref],
        }

    names = ["generate", "search", "download", "properties", "check", "export", "db_query"]
    descriptions = {
        "generate":"Generate structures with one of the ten structure generators.", "search":"Search local or Materials Project sources.",
        "download":"Download a referenced structure into the local cache.", "properties":"Query cached material properties.",
        "check":"Run lightweight structural checks.", "export":"Export structures as POSCAR, CIF, or LAMMPS data.", "db_query":"Query local database snapshots."}
    definitions = [
        ToolDefinition(n, descriptions[n], None, None, _placeholder(n), n in {"generate", "download", "export"})
        for n in names
    ]
    definitions.extend([
        ToolDefinition(
            "generate_surface",
            "Generate all bounded surface terminations and return candidate metadata for user selection.",
            GenerateSurfaceArguments,
            None,
            generate_surface,
            True,
        ),
        ToolDefinition(
            "generate_adsorption",
            "Generate adsorption structures from a prepared slab and adsorbate molecule.",
            GenerateAdsorptionArguments,
            None,
            generate_adsorption,
            True,
        ),
        ToolDefinition("cases_status", "Read adsorption case index status.", CasesStatusArguments, None, cases_status),
        ToolDefinition("cases_query", "Query indexed adsorption case revisions.", CasesQueryArguments, None, cases_query),
        ToolDefinition("cases_inspect", "Inspect one indexed adsorption case revision.", CasesInspectArguments, None, cases_inspect),
        ToolDefinition(
            "revision_import",
            "Import an audited coordinate-only structure revision into the fixed output root.",
            RevisionImportArguments,
            None,
            revision_import,
            True,
        ),
    ])
    return ToolRegistry(definitions)
