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


_COVALENT_RADII = {"H": 0.31, "C": 0.76, "N": 0.71, "O": 0.66, "S": 1.05, "P": 1.07}


def _covalent_radius(symbol: str) -> float:
    return _COVALENT_RADII.get(symbol, 1.25)


class _AdsorptionModel(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", frozen=True)


class AdsorptionInput(_AdsorptionModel):
    """A slab and an adsorbate with a CLI-facing, one-based anchor index."""

    slab: Structure
    molecule: Molecule | Structure
    anchor_index: PositiveInt = Field(description="One-based atom index in the adsorbate")
    gas_reference: Molecule | Structure | None = None
    input_source: str = "in-memory"
    input_structure_hash: str | None = None
    reference_axis: tuple[float, float, float] | None = None
    denticity: PositiveInt = 1
    rigid: bool = True
    charge: int | None = None
    spin_multiplicity: PositiveInt | None = None

    @field_validator("reference_axis")
    @classmethod
    def finite_reference_axis(cls, value):
        if value is None:
            return None
        array = np.asarray(value, dtype=float)
        if array.shape != (3,) or not np.isfinite(array).all() or np.linalg.norm(array) <= 1e-12:
            raise ValueError("reference axis must be a non-zero finite vector")
        return tuple(float(item) for item in array)

    @model_validator(mode="after")
    def validate_input(self) -> "AdsorptionInput":
        if len(self.slab) == 0 or len(self.molecule) == 0:
            raise ValueError("slab and molecule must contain at least one atom")
        if self.anchor_index > len(self.molecule):
            raise ValueError("anchor_index is outside the adsorbate")
        coords = np.asarray(self.molecule.cart_coords, dtype=float)
        if not np.isfinite(coords).all():
            raise ValueError("molecule coordinates must be finite")
        if self.denticity != 1:
            raise ValueError("only a single-anchor adsorbate is supported")
        if not self.rigid:
            raise ValueError("only rigid adsorbates are supported")
        if len(self.molecule) > 1 and self.reference_axis is None:
            raise ValueError("multi-atom adsorbate requires reference axis")
        molecule_charge = int(round(float(getattr(self.molecule, "charge", 0))))
        if self.charge is None:
            object.__setattr__(self, "charge", molecule_charge)
        elif self.charge != molecule_charge:
            raise ValueError("charge must match the adsorbate molecule")
        molecule_spin = int(getattr(self.molecule, "spin_multiplicity", 1))
        if self.spin_multiplicity is None:
            object.__setattr__(self, "spin_multiplicity", molecule_spin)
        elif self.spin_multiplicity != molecule_spin:
            raise ValueError("spin multiplicity must match the adsorbate molecule")
        if len(self.molecule) > 1:
            adjacency = [set() for _ in range(len(self.molecule))]
            for left in range(len(self.molecule)):
                for right in range(left + 1, len(self.molecule)):
                    symbols = (str(self.molecule[left].specie), str(self.molecule[right].specie))
                    if self.molecule.get_distance(left, right) <= 1.25 * sum(_covalent_radius(symbol) for symbol in symbols):
                        adjacency[left].add(right)
                        adjacency[right].add(left)
            seen: set[int] = set()
            stack = [self.anchor_index_zero_based]
            while stack:
                current = stack.pop()
                if current in seen:
                    continue
                seen.add(current)
                stack.extend(adjacency[current] - seen)
            if len(seen) != len(self.molecule):
                raise ValueError("adsorbate bond graph must be connected")
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
    history_policy: Literal["off", "prefer", "require"] | None = None
    site_types: tuple[str, ...] | None = None
    explicit_sites: tuple[tuple[float, float, float], ...] = ()
    max_proposal_attempts: PositiveInt | None = None
    anchor_contact_window: tuple[float, float] | None = None
    azimuths: tuple[float, ...] = (0.0,)
    tilts: tuple[float, ...] = (0.0,)
    rolls: tuple[float, ...] = (0.0,)
    heights: tuple[float, ...] | None = None
    layer_tolerance: PositiveFloat = 0.15
    coverage: float | None = Field(default=None, gt=0.0, le=1.0)
    min_vacuum_each_side: float = Field(default=0.0, ge=0.0)

    @field_validator("site_height")
    @classmethod
    def finite_height(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("site_height must be finite")
        return value

    @field_validator("azimuths", "tilts", "rolls")
    @classmethod
    def finite_pose_set(cls, value):
        if not value or not all(math.isfinite(float(item)) for item in value):
            raise ValueError("pose sets must be non-empty and finite")
        return tuple(float(item) for item in value)

    @field_validator("explicit_sites")
    @classmethod
    def finite_explicit_sites(cls, value):
        normalized = tuple(tuple(float(item) for item in position) for position in value)
        if any(len(position) != 3 or not np.isfinite(position).all() for position in normalized):
            raise ValueError("explicit Cartesian sites must contain finite triplets")
        return normalized

    @model_validator(mode="after")
    def normalize_aliases(self):
        if self.history_policy is not None:
            object.__setattr__(self, "history_mode", self.history_policy)
        if self.site_types is not None:
            allowed = {"ontop", "top", "bridge", "hollow", "hollow4", "defect", "doped", "undercoordinated", "explicit"}
            if not self.site_types or not set(self.site_types) <= allowed:
                raise ValueError("site_types contains an unsupported adsorption site type")
            object.__setattr__(self, "site_kinds", tuple("ontop" if item == "top" else item for item in self.site_types))
        if self.max_proposal_attempts is not None:
            if self.max_attempts is not None and self.max_attempts != self.max_proposal_attempts:
                raise ValueError("max_attempts and max_proposal_attempts disagree")
            object.__setattr__(self, "max_attempts", self.max_proposal_attempts)
        if self.heights is not None:
            if not self.heights or not all(math.isfinite(float(item)) and float(item) > 0 for item in self.heights):
                raise ValueError("heights must be finite and positive")
            object.__setattr__(self, "site_height", float(self.heights[0]))
        if self.anchor_contact_window is not None:
            lower, upper = self.anchor_contact_window
            if not math.isfinite(lower) or not math.isfinite(upper) or not 0 < lower < upper:
                raise ValueError("anchor contact window must be finite and increasing")
        if self.max_attempts is not None and self.max_attempts < self.max_structures:
            raise ValueError("max_attempts must not be below max_structures")
        if self.max_structures > 100_000 or (self.max_attempts is not None and self.max_attempts > 1_000_000):
            raise ValueError("adsorption generation bounds are too large")
        return self


class StructureContext(_AdsorptionModel):
    """Structural roles and constraints retained with adsorption outputs."""

    matrix: tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]
    vacuum_axis: int = Field(default=2, ge=0, le=2)
    notes: tuple[str, ...] = ()
    comparison_roles: tuple[str, ...] = ("clean_slab", "adsorbed", "gas_reference")
    fixed_layers: int = 0
    surface_side: Literal["top", "bottom", "both"] = "top"
    coverage: float | None = None

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
    structure_context: StructureContext | None = None
    actual_parameters: dict[str, Any] = Field(default_factory=dict)
    clean_slab: Structure | None = None
    adsorbate: Molecule | Structure | None = None
    gas_reference: Molecule | Structure | None = None
    retrieval_trace: Any | None = None
    proposal_audit: Any | None = None
    validation_reports: tuple[Any, ...] = ()

    def combine(self, other: "AdsorptionGenerationResult") -> "AdsorptionGenerationResult":
        if self.clean_slab is None or other.clean_slab is None or structure_sha256(self.clean_slab) != structure_sha256(other.clean_slab):
            raise ValueError("cannot combine adsorption results from different slabs")
        if self.adsorbate is None or other.adsorbate is None or repr(self.adsorbate) != repr(other.adsorbate):
            raise ValueError("cannot combine adsorption results from different adsorbates")
        if self.structure_context != other.structure_context:
            raise ValueError("cannot combine adsorption results with different structure contexts")
        return self.model_copy(update={
            "generated": (*self.generated, *other.generated),
            "warnings": (*self.warnings, *other.warnings),
            "validation_reports": (*self.validation_reports, *other.validation_reports),
        })


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
            reference_axis=inputs.reference_axis or (0.0, 0.0, 1.0),
            azimuths=params.azimuths,
            tilts=params.tilts,
            rolls=params.rolls,
            heights=params.heights,
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
        explicit = tuple((f"explicit-{index:04d}", coords) for index, coords in enumerate(params.explicit_sites))
        proposals = selected_source.iter_proposals(site_kinds=params.site_kinds, side=params.surface_side, explicit_sites=explicit or None) if selected_source is algorithmic else selected_source.iter_proposals()
        attempts = params.max_attempts or max(params.max_structures * 20, params.max_structures)
        candidates, audit = bounded_proposal_stream(proposals, max_attempts=attempts)
        generated: list[GeneratedStructure] = []
        warnings: list[str] = []
        if fallback_reason:
            warnings.append(fallback_reason)
        parent_id = structure_sha256(inputs.slab)
        validator = AdsorptionCandidateValidator(
            inputs.slab,
            algorithmic.molecule,
            anchor_index=inputs.anchor_index_zero_based,
            anchor_contact_window=params.anchor_contact_window,
            max_coverage=params.coverage,
            min_vacuum_each_side=params.min_vacuum_each_side,
        )
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
