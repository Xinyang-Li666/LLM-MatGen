"""Unified source-to-generator-to-export application service."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, ValidationError

from llm_matgen.generators import (
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


@dataclass(frozen=True)
class GeneratorEntry:
    factory: type
    params_model: type[BaseModel]
    binary: bool = False


@dataclass
class ServiceResult:
    runs: list[PipelineResult]

    @property
    def ok(self) -> bool:
        return bool(self.runs) and all(run.ok for run in self.runs)


def default_generator_registry() -> dict[str, GeneratorEntry]:
    return {
        "vacancy": GeneratorEntry(VacancyGenerator, VacancyParams),
        "interstitial": GeneratorEntry(InterstitialGenerator, InterstitialParams),
        "doping": GeneratorEntry(DopingGenerator, DopingParams),
        "solid-solution": GeneratorEntry(SolidSolutionGenerator, SolidSolutionParams),
        "surface": GeneratorEntry(SurfaceGenerator, SurfaceParams),
        "grain-boundary": GeneratorEntry(GrainBoundaryGenerator, GrainBoundaryParams),
        "interface": GeneratorEntry(InterfaceGenerator, InterfaceParams, binary=True),
        "stacking-fault": GeneratorEntry(StackingFaultGenerator, StackingFaultParams),
        "dislocation": GeneratorEntry(DislocationGenerator, DislocationParams),
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
        expected_inputs = 2 if entry.binary else None
        if expected_inputs is not None and len(request.input_refs) != expected_inputs:
            raise GenerationServiceError("interface generation requires exactly two input structures")

        parameters = dict(request.parameters)
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

        resolved = [self.source.get(reference) for reference in request.input_refs]
        for item in resolved:
            if len(item.structure) > request.limits.max_atoms_per_structure:
                raise GenerationServiceError(
                    f"input atom limit exceeded: {len(item.structure)} > "
                    f"{request.limits.max_atoms_per_structure}"
                )

        pipeline = GenerationPipeline(request.limits.output_root)
        generator = entry.factory()
        runs: list[PipelineResult] = []
        if entry.binary:
            inputs = InterfaceInput(
                film=resolved[0].structure,
                substrate=resolved[1].structure,
            )
            runs.append(
                pipeline.run(generator, inputs, params, request.export_options)
            )
        else:
            for item in resolved:
                runs.append(
                    pipeline.run(generator, item.structure, params, request.export_options)
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
