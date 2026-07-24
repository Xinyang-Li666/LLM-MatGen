from pymatgen.core import Lattice, Structure


def make_fixture() -> Structure:
    return Structure(
        Lattice.cubic(4.2),
        ["Li", "Co", "O", "O"],
        [[0, 0, 0], [0.5, 0.5, 0.5], [0.5, 0.5, 0], [0.5, 0, 0.5]],
    )


def test_structure_hash_is_stable_and_sensitive_to_coordinates():
    from llm_matgen.utils.structure import structure_sha256

    structure = make_fixture()
    assert structure_sha256(structure) == structure_sha256(structure.copy())

    changed = structure.copy()
    changed.translate_sites([0], [0.01, 0, 0], frac_coords=True)
    assert structure_sha256(changed) != structure_sha256(structure)


def test_site_ids_are_stable_and_include_parent_identity():
    from llm_matgen.utils.structure import assign_site_ids, structure_sha256

    structure = make_fixture()
    parent_hash = structure_sha256(structure)
    first = assign_site_ids(structure, parent_hash)
    second = assign_site_ids(structure.copy(), parent_hash)

    assert first == second
    assert len(first) == len(structure)
    assert len(set(first)) == len(structure)
    assert all(parent_hash[:12] in site_id for site_id in first)


def test_canonical_payload_normalizes_fractional_coordinates_but_not_site_order():
    from llm_matgen.utils.structure import canonical_structure_payload

    structure = make_fixture()
    shifted = structure.copy()
    shifted.translate_sites([0], [1, 0, 0], frac_coords=True)

    assert canonical_structure_payload(structure) == canonical_structure_payload(shifted)

    reordered = Structure(
        structure.lattice,
        list(reversed([site.specie for site in structure])),
        list(reversed([site.frac_coords for site in structure])),
    )
    assert canonical_structure_payload(structure) != canonical_structure_payload(reordered)
