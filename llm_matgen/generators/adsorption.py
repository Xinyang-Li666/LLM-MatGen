"""Contracts shared by adsorption proposal, validation and generation stages.

The models in this module deliberately contain no generation policy.  They are
the small, serialisable boundary between a slab/molecule input, configurable
sampling limits, and the information handed to a downstream DFT workflow.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Iterable, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, PositiveFloat, PositiveInt, field_validator, model_validator
from pymatgen.core import Molecule, Structure

from llm_matgen.adsorption.proposals import (
    AlgorithmicProposalSource,
    RetrievedProposalSource,
    bounded_proposal_stream,
    resolve_history,
)
from llm_matgen.adsorption.validation import AdsorptionCandidateValidator, apply_fixed_bottom_layers
from llm_matgen.generators.models import GeneratedStructure, GenerationResult, Provenance, StructureRecord
from llm_matgen.utils.structure import structure_sha256


class _AdsorptionModel(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", frozen=True)


class AdsorptionInput(_AdsorptionModel):
    """A slab and an adsorbate with a CLI-facing, one-based anchor index."""

    slab: Structure
    molecule: Molecule | Structure
    anchor_index: PositiveInt = Field(description="One-based atom index in the adsorbate")

    @model_validator(mode="after")
    def validate_input(self) -> "AdsorptionInput":
        if len(self.slab) == 0 or len(self.molecule) == 0:
            raise ValueError("slab and molecule must contain at least one atom")
        if self.anchor_index > len(self.molecule):
            raise ValueError("anchor_index is outside the adsorbate")
        coords = np.asarray(self.molecule.cart_coords, dtype=float)
        if not np.isfinite(coords).all():
            raise ValueError("molecule coordinates must be finite")
        return self

    @property
    def anchor_index_zero_based(self) -> int:
        return self.anchor_index - 1


class AdsorptionParams(_AdsorptionModel):
    """Bounded generation controls; all counts are intentionally finite."""

    site_height: PositiveFloat = 2.0
    max_structures: PositiveInt = 1000
    max_atoms_per_structure: PositiveInt = 10000
    history_mode: Literal["off", "prefer", "require"] = "off"
    site_kinds: tuple[str, ...] = ("ontop", "bridge", "hollow")
    surface_side: Literal["top", "bottom", "both"] = "top"
    fixed_bottom_layers: int = Field(default=0, ge=0)
    preview: bool = False
    max_attempts: PositiveInt | None = None

    @field_validator("site_height")
    @classmethod
    def finite_height(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("site_height must be finite")
        return value


class DFTHandoffMatrix(_AdsorptionModel):
    """Explicit handoff metadata so DFT setup assumptions are not implicit."""

    matrix: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]
    vacuum_axis: int = Field(default=2, ge=0, le=2)
    notes: tuple[str, ...] = ()

    @field_validator("matrix")
    @classmethod
    def valid_matrix(cls, value: Any):
        array = np.asarray(value, dtype=float)
        if array.shape != (3, 3) or not np.isfinite(array).all():
            raise ValueError("matrix must be a finite 3x3 matrix")
        if abs(float(np.linalg.det(array))) < 1e-12:
            raise ValueError("matrix must be nonsingular")
        return tuple(tuple(float(component) for component in row) for row in array)


class AdsorptionGenerationResult(_AdsorptionModel):
    """Stable result envelope used by later generator and pipeline stages."""

    generated: tuple[Structure, ...] = ()
    warnings: tuple[str, ...] = ()
    dft_handoff: DFTHandoffMatrix | None = None
    actual_parameters: dict[str, Any] = Field(default_factory=dict)


class AdsorptionGenerator:
    defect_name = "adsorption"
    generator_version = "0.2.0"

    def __init__(self, history: Iterable | None = None):
        self.history = tuple(history) if history is not None else None

    def generate(self, inputs: AdsorptionInput, params: AdsorptionParams) -> GenerationResult:
        algorithmic = AlgorithmicProposalSource(
            inputs.slab,
            inputs.molecule if isinstance(inputs.molecule, Molecule) else Molecule(inputs.molecule.species, inputs.molecule.cart_coords),
            height=float(params.site_height),
            anchor_index=inputs.anchor_index_zero_based,
        )
        history_source = None
        if params.history_mode != "off" and self.history:
            history_source = RetrievedProposalSource(
                inputs.slab,
                algorithmic.molecule,
                self.history,
                height=float(params.site_height),
                anchor_index=inputs.anchor_index_zero_based,
            )
        selected_source, fallback_reason = resolve_history(params.history_mode, history_source, algorithmic)
        proposals = selected_source.iter_proposals(site_kinds=params.site_kinds, side=params.surface_side) if selected_source is algorithmic else selected_source.iter_proposals()
        attempts = params.max_attempts or max(params.max_structures * 20, params.max_structures)
        candidates, audit = bounded_proposal_stream(proposals, max_attempts=attempts)
        generated: list[GeneratedStructure] = []
        warnings: list[str] = []
        if fallback_reason:
            warnings.append(fallback_reason)
        parent_id = structure_sha256(inputs.slab)
        validator = AdsorptionCandidateValidator(inputs.slab, algorithmic.molecule)
        for proposal in candidates:
            species = [site.specie for site in inputs.slab] + list(algorithmic.molecule.species)
            coords = np.vstack([inputs.slab.cart_coords, proposal.adsorbate_coords])
            candidate = Structure(inputs.slab.lattice, species, coords, coords_are_cartesian=True)
            fixed = apply_fixed_bottom_layers(
                candidate,
                slab_atom_count=len(inputs.slab),
                n_layers=params.fixed_bottom_layers,
                side="bottom",
            )
            candidate.add_site_property("selective_dynamics", list(fixed.flags))
            report = validator.validate(candidate, expected_flags=fixed.flags)
            if not report.valid:
                warnings.extend(issue.code for issue in report.issues)
                continue
            child_id = structure_sha256(candidate)
            if any(item.record.structure_id == child_id for item in generated):
                warnings.append("duplicate adsorption candidate skipped")
                continue
            generated.append(
                GeneratedStructure(
                    candidate,
                    StructureRecord(
                        structure_id=child_id,
                        parent_structure_id=parent_id,
                        formula=candidate.composition.reduced_formula,
                        n_atoms=len(candidate),
                        actual_parameters={
                            "proposal": {"site_id": proposal.site_id, "site_kind": proposal.site_kind, "side": proposal.side, "source": proposal.source},
                            "validation": report.measurements,
                            "fixed_layers": params.fixed_bottom_layers,
                        },
                        site_mapping={},
                    ),
                )
            )
            if len(generated) >= params.max_structures:
                break
        if not generated and params.history_mode == "require":
            raise ValueError("history proposals produced no valid adsorption candidate")
        if not generated:
            raise ValueError("adsorption generation produced no valid candidates")
        if audit.truncated:
            warnings.append("adsorption proposal attempts truncated")
        return GenerationResult(
            defect_type=self.defect_name,
            input_count=1,
            generated=generated,
            warnings=warnings,
            provenance=Provenance(
                generator=self.defect_name,
                generator_version=self.generator_version,
                input_source="in-memory",
                input_structure_hash=parent_id,
                parameters=params.model_dump(mode="json"),
                seed=None,
                created_at=datetime.now(timezone.utc),
            ),
        )
