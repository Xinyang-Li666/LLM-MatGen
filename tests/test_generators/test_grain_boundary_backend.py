import pytest
from pymatgen.core import Lattice, Structure


def fixture_structure() -> Structure:
    return Structure(Lattice.cubic(3.6), ["Cu"], [[0, 0, 0]])


def test_pymatgen_grain_boundary_backend_forwards_contract(monkeypatch):
    from llm_matgen.generators import backends

    calls = {}

    class FakeBuilder:
        def __init__(self, structure):
            calls["structure"] = structure

        def gb_from_parameters(self, **kwargs):
            calls.update(kwargs)
            return fixture_structure().copy()

    monkeypatch.setattr(backends, "PymatgenGBBuilder", FakeBuilder)
    result = backends.PymatgenGrainBoundaryBackend().generate(
        fixture_structure(),
        rotation_axis=(0, 0, 1),
        rotation_angle=36.87,
        plane=(1, 2, 0),
        expand_times=2,
        vacuum_thickness=1.5,
        ab_shift=(0.1, 0.2),
    )
    assert result.structure.num_sites == 1
    assert calls["rotation_axis"] == (0, 0, 1)
    assert calls["rotation_angle"] == 36.87
    assert result.actual_parameters["rotation_angle"] == 36.87


def test_grain_boundary_backend_rejects_empty_result(monkeypatch):
    from llm_matgen.generators import backends

    class FakeBuilder:
        def __init__(self, structure):
            pass

        def gb_from_parameters(self, **kwargs):
            return None

    monkeypatch.setattr(backends, "PymatgenGBBuilder", FakeBuilder)
    with pytest.raises(backends.BackendGenerationError, match="no structure"):
        backends.PymatgenGrainBoundaryBackend().generate(
            fixture_structure(),
            rotation_axis=(0, 0, 1),
            rotation_angle=36.87,
            plane=None,
            expand_times=2,
            vacuum_thickness=0,
            ab_shift=(0, 0),
        )
