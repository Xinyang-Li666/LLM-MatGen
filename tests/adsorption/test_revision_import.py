import json
from pathlib import Path

import pytest
from pymatgen.core import Lattice, Structure


def _structures():
    parent = Structure(Lattice.cubic(4), ["Cu", "H"], [[0, 0, 0], [0.5, 0.5, 0.5]])
    child = parent.copy()
    child.translate_sites([1], [0.01, 0, 0], frac_coords=True)
    return parent, child


def test_v1_normalizes_to_v2_change_list_and_imports_atom_coordinate_only(tmp_path: Path):
    from llm_matgen.adsorption.revision import RevisionImporter, RevisionSidecarV1, normalize_revision
    from llm_matgen.utils.structure import structure_sha256

    parent, child = _structures()
    v1 = RevisionSidecarV1(parent_hash=structure_sha256(parent), child_hash=structure_sha256(child), atom_index=1, old_frac_coords=tuple(parent.frac_coords[1]), new_frac_coords=tuple(child.frac_coords[1]), reason="manual")
    normalized = normalize_revision(v1)
    assert normalized.version == 2 and len(normalized.changes) == 1
    result = RevisionImporter(tmp_path).import_revision(parent, child, normalized)
    assert (result.path / "child.POSCAR").exists()
    assert json.loads((result.path / "manifest.json").read_text())['version'] == 2


def test_revision_rejects_duplicate_index_and_existing_destination(tmp_path: Path):
    from llm_matgen.adsorption.revision import RevisionImporter, RevisionSidecarV2, RevisionChange
    from llm_matgen.utils.structure import structure_sha256

    parent, child = _structures()
    kwargs = dict(parent_hash=structure_sha256(parent), child_hash=structure_sha256(child), reason="manual")
    with pytest.raises(ValueError, match="duplicate"):
        RevisionSidecarV2(changes=(RevisionChange(atom_index=1, old_frac_coords=tuple(parent.frac_coords[1]), new_frac_coords=tuple(child.frac_coords[1])), RevisionChange(atom_index=1, old_frac_coords=tuple(parent.frac_coords[1]), new_frac_coords=tuple(child.frac_coords[1]))), **kwargs)
