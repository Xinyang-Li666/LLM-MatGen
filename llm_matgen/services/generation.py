"""Unified source-to-generator-to-export application service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, ValidationError

from llm_matgen.generators import (
    AdsorptionGenerator,
    AdsorptionInput,
    AdsorptionParams,
    DislocationGenerator,
    DislocationParams,
    DopingGenerator,
    DopingParams,
    GrainBoundaryGenerator,
    GrainBoundaryParams,
    InterfaceGenerator,
    InterfaceInput,
    InterfaceParams,
    InterstitialGenerator,
    InterstitialParams,
    SolidSolutionGenerator,
    SolidSolutionParams,
    StackingFaultGenerator,
    StackingFaultParams,
    SurfaceGenerator,
    SurfaceParams,
    VacancyGenerator,
    VacancyParams,
)
from llm_matgen.io.exporters import ExportOptions
from llm_matgen.pipeline import GenerationPipeline, PipelineResult
from llm_matgen.sources.models import StructureSource


class GenerationServiceError(ValueError):
    pass


class ExecutionLimits(BaseModel):
    max_structures: PositiveInt = 1000
    max_atoms_per_structure: PositiveInt = 100_000
    output_root: Path


class GenerationRequest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    generator: str
    input_refs: list[str] = Field(min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    export_options: ExportOptions = Field(default_factory=ExportOptions)
    limits: ExecutionLimits
    viewer: bool = True


@dataclass(frozen=True)
class GeneratorEntry:
    factory: type
    params_model: type[BaseModel]
    inputs: tuple["GeneratorInputSpec", ...]


@dataclass(frozen=True)
class GeneratorInputSpec:
    role: str
    kind: str
    cardinality: str = "one"


@dataclass
class ServiceResult:
    runs: list[PipelineResult]

    @property
    def ok(self) -> bool:
        return bool(self.runs) and all(run.ok for run in self.runs)


def default_generator_registry() -> dict[str, GeneratorEntry]:
    unary = (GeneratorInputSpec("structure", "structure", "many"),)
    return {
        "vacancy": GeneratorEntry(VacancyGenerator, VacancyParams, unary),
        "interstitial": GeneratorEntry(InterstitialGenerator, InterstitialParams, unary),
        "doping": GeneratorEntry(DopingGenerator, DopingParams, unary),
        "solid-solution": GeneratorEntry(SolidSolutionGenerator, SolidSolutionParams, unary),
        "surface": GeneratorEntry(SurfaceGenerator, SurfaceParams, unary),
        "grain-boundary": GeneratorEntry(GrainBoundaryGenerator, GrainBoundaryParams, unary),
        "interface": GeneratorEntry(InterfaceGenerator, InterfaceParams, (
            GeneratorInputSpec("film", "structure"), GeneratorInputSpec("substrate", "structure"),
        )),
        "stacking-fault": GeneratorEntry(StackingFaultGenerator, StackingFaultParams, unary),
        "dislocation": GeneratorEntry(DislocationGenerator, DislocationParams, unary),
        "adsorption": GeneratorEntry(AdsorptionGenerator, AdsorptionParams, (
            GeneratorInputSpec("slab", "structure"), GeneratorInputSpec("adsorbate", "molecule"),
        )),
    }


class GenerationService:
    def __init__(
        self,
        source: StructureSource,
        *,
        registry: dict[str, GeneratorEntry] | None = None,
    ):
        self.source = source
        self.registry = registry or default_generator_registry()

    def run(self, request: GenerationRequest) -> ServiceResult:
        entry = self.registry.get(request.generator)
        if entry is None:
            raise GenerationServiceError(f"unknown generator: {request.generator}")
        repeated_unary = len(entry.inputs) == 1 and entry.inputs[0].cardinality == "many"
        if not repeated_unary and len(request.input_refs) != len(entry.inputs):
            if request.generator == "interface":
                raise GenerationServiceError("interface generation requires exactly two input structures")
            roles = ", ".join(spec.role for spec in entry.inputs)
            raise GenerationServiceError(f"{request.generator} requires inputs in order: {roles}")
        if repeated_unary and not request.input_refs:
            raise GenerationServiceError(f"{request.generator} requires at least one input structure")

        input_parameters = {}
        if request.generator == "adsorption":
            for key in ("anchor_index", "reference_axis", "charge", "spin_multiplicity", "denticity", "rigid"):
                if key in request.parameters:
                    input_parameters[key] = request.parameters[key]

        parameters = {key: value for key, value in request.parameters.items() if key not in input_parameters}
        for name, limit in (
            ("max_structures", request.limits.max_structures),
            ("max_atoms_per_structure", request.limits.max_atoms_per_structure),
        ):
            requested = parameters.get(name)
            if requested is not None and requested > limit:
                raise GenerationServiceError(f"requested {name} exceeds execution limit")
            parameters[name] = min(requested, limit) if requested is not None else limit
        try:
            params = entry.params_model.model_validate(parameters)
        except ValidationError as exc:
            raise GenerationServiceError(f"invalid generator parameters: {exc}") from exc

        if repeated_unary:
            resolved = [self.source.get(reference) for reference in request.input_refs]
        else:
            resolved = []
            for spec, reference in zip(entry.inputs, request.input_refs, strict=True):
                resolver = self.source.get if spec.kind == "structure" else getattr(self.source, "get_molecule", None)
                if resolver is None:
                    raise GenerationServiceError(f"source cannot resolve {spec.kind} role {spec.role}")
                resolved.append(resolver(reference))
        for item in resolved:
            value = getattr(item, "structure", None) or getattr(item, "molecule", None)
            if len(value) > request.limits.max_atoms_per_structure:
                raise GenerationServiceError(
                    f"input atom limit exceeded: {len(value)} > "
                    f"{request.limits.max_atoms_per_structure}"
                )

        pipeline = GenerationPipeline(request.limits.output_root)
        generator = entry.factory()
        runs: list[PipelineResult] = []
        if request.generator == "interface":
            inputs = InterfaceInput(
                film=resolved[0].structure,
                substrate=resolved[1].structure,
            )
            runs.append(
                pipeline.run(generator, inputs, params, request.export_options, viewer=request.viewer)
            )
        elif request.generator == "adsorption":
            inputs = AdsorptionInput(
                slab=resolved[0].structure,
                molecule=resolved[1].molecule,
                anchor_index=input_parameters.pop("anchor_index", 1),
                **input_parameters,
            )
            runs.append(pipeline.run(generator, inputs, params, request.export_options, viewer=request.viewer))
        else:
            for item in resolved:
                runs.append(
                    pipeline.run(generator, item.structure, params, request.export_options, viewer=request.viewer)
                )
        for run in runs:
            if run.generation.generated_count > request.limits.max_structures:
                raise GenerationServiceError("generated structure count exceeds execution limit")
            if any(
                len(item.structure) > request.limits.max_atoms_per_structure
                for item in run.generation.generated
            ):
                raise GenerationServiceError("generated structure atom limit exceeded")
        return ServiceResult(runs=runs)
