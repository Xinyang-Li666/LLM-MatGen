"""Two-parent contracts for coherent interface generation."""

from __future__ import annotations

from dataclasses import dataclass

from pymatgen.core import Structure

from llm_matgen.utils.structure import assign_site_ids, structure_sha256


@dataclass(frozen=True)
class InterfaceInput:
    film: Structure
    substrate: Structure


@dataclass(frozen=True)
class BinaryLineage:
    parent_structure_ids: dict[str, str]
    site_mapping: dict[str, str | None]


def build_binary_lineage(inputs: InterfaceInput) -> BinaryLineage:
    film_id = structure_sha256(inputs.film)
    substrate_id = structure_sha256(inputs.substrate)
    mapping: dict[str, str | None] = {}
    for site_id in assign_site_ids(inputs.film, film_id):
        mapping[f"film:{site_id}"] = None
    for site_id in assign_site_ids(inputs.substrate, substrate_id):
        mapping[f"substrate:{site_id}"] = None
    return BinaryLineage(
        parent_structure_ids={"film": film_id, "substrate": substrate_id},
        site_mapping=mapping,
    )
