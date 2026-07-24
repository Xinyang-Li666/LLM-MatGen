"""Deterministic structure identity and site lineage helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np
from pymatgen.core import Structure

_DECIMALS = 10


def _rounded(values: Any) -> Any:
    return np.asarray(values, dtype=float).round(_DECIMALS).tolist()


def canonical_structure_payload(structure: Structure) -> dict[str, Any]:
    """Return an order-sensitive, translation-normalized JSON payload."""
    sites = []
    for site in structure:
        species = {
            str(element): round(float(occupancy), _DECIMALS)
            for element, occupancy in sorted(site.species.items(), key=lambda item: str(item[0]))
        }
        sites.append(
            {
                "species": species,
                "frac_coords": _rounded(np.mod(site.frac_coords, 1.0)),
            }
        )
    return {
        "lattice": _rounded(structure.lattice.matrix),
        "sites": sites,
    }


def structure_sha256(structure: Structure) -> str:
    payload = canonical_structure_payload(structure)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def assign_site_ids(structure: Structure, parent_structure_id: str) -> list[str]:
    """Assign stable IDs based on parent identity, order, and species."""
    parent_token = parent_structure_id[:12]
    return [
        f"site-{parent_token}-{index:05d}-{str(site.specie)}"
        for index, site in enumerate(structure)
    ]
