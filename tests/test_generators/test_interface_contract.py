from pymatgen.core import Lattice, Structure
from datetime import datetime, timezone


def film_structure() -> Structure:
    return Structure(Lattice.cubic(3.5), ["Ni"], [[0, 0, 0]])


def substrate_structure() -> Structure:
    return Structure(Lattice.cubic(3.6), ["Cu"], [[0, 0, 0]])


def test_interface_input_keeps_two_parents_distinct():
    from llm_matgen.generators.interface import InterfaceInput, build_binary_lineage

    inputs = InterfaceInput(film=film_structure(), substrate=substrate_structure())
    lineage = build_binary_lineage(inputs)
    assert lineage.parent_structure_ids.keys() == {"film", "substrate"}
    assert lineage.parent_structure_ids["film"] != lineage.parent_structure_ids["substrate"]
    assert all(key.startswith("film:") or key.startswith("substrate:") for key in lineage.site_mapping)


def test_binary_generator_protocol_accepts_generate_shape():
    from llm_matgen.generators.base import BinaryStructureGenerator

    class FakeBinaryGenerator:
        def generate(self, inputs, params):
            return None

    assert isinstance(FakeBinaryGenerator(), BinaryStructureGenerator)


def test_core_records_support_named_multiple_parents():
    from llm_matgen.generators.models import Provenance, StructureRecord

    parent_ids = {"film": "film-hash", "substrate": "substrate-hash"}
    record = StructureRecord(
        structure_id="child",
        parent_structure_id="substrate-hash",
        parent_structure_ids=parent_ids,
        formula="CuNi",
        n_atoms=2,
        actual_parameters={},
        site_mapping={},
    )
    provenance = Provenance(
        generator="interface",
        generator_version="0.1.0",
        input_source="in-memory",
        input_structure_hash="substrate-hash",
        input_structure_hashes=parent_ids,
        parameters={},
        seed=None,
        created_at=datetime.now(timezone.utc),
    )
    assert record.parent_structure_ids == parent_ids
    assert provenance.input_structure_hashes == parent_ids
