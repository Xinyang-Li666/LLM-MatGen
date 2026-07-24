from pymatgen.core import Lattice, Structure

from llm_matgen.generators.backends import BackendStructure


def film_structure() -> Structure:
    return Structure(Lattice.cubic(3.5), ["Ni"], [[0, 0, 0]])


def substrate_structure() -> Structure:
    return Structure(Lattice.cubic(3.6), ["Cu"], [[0, 0, 0]])


def combined_structure(shift: float = 0.0) -> Structure:
    return Structure(
        Lattice.from_parameters(3.6, 3.6, 12.0, 90, 90, 90),
        ["Cu", "Ni"],
        [[0, 0, 0.25], [shift, 0, 0.65]],
    )


class FakeInterfaceBackend:
    def generate(self, inputs, **kwargs):
        return [
            BackendStructure(combined_structure(0.02), {"interface_area": 14.0, "mismatch": 0.02}),
            BackendStructure(combined_structure(0.08), {"interface_area": 12.0, "mismatch": 0.08}),
        ]


def make_params(**updates):
    from llm_matgen.generators.interface import InterfaceParams

    values = dict(
        film_millers=[(0, 0, 1)],
        substrate_millers=[(0, 0, 1)],
        film_thickness=4.0,
        substrate_thickness=4.0,
        vacuum_thickness=4.0,
        gap=2.0,
        max_area=100.0,
        max_area_ratio_tol=0.1,
        max_length_tol=0.05,
        max_angle_tol=0.02,
    )
    values.update(updates)
    return InterfaceParams(**values)


def test_interface_sorts_candidates_and_records_two_parent_lineage():
    from llm_matgen.generators.interface import InterfaceGenerator, InterfaceInput

    result = InterfaceGenerator(backend=FakeInterfaceBackend()).generate(
        InterfaceInput(film=film_structure(), substrate=substrate_structure()),
        make_params(),
    )
    assert result.generated_count == 2
    assert [item.record.actual_parameters["interface_area"] for item in result.generated] == [12.0, 14.0]
    record = result.generated[0].record
    assert record.parent_structure_ids.keys() == {"film", "substrate"}
    assert all(key.startswith("film:") or key.startswith("substrate:") for key in record.site_mapping)
    assert result.provenance.input_structure_hashes == record.parent_structure_ids


def test_interface_enforces_atom_limit():
    import pytest
    from llm_matgen.generators.interface import InterfaceGenerator, InterfaceInput

    with pytest.raises(ValueError, match="atom limit"):
        InterfaceGenerator(backend=FakeInterfaceBackend()).generate(
            InterfaceInput(film=film_structure(), substrate=substrate_structure()),
            make_params(max_atoms_per_structure=1),
        )
