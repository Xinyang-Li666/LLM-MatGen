from pymatgen.core import Lattice, Structure

from llm_matgen.generators.backends import BackendStructure


def source() -> Structure:
    return Structure(
        Lattice.cubic(4.0),
        ["Al", "Al"],
        [[0.25, 0.25, 0.25], [0.25, 0.25, 0.75]],
    )


class GrainBackend:
    def generate(self, structure, **kwargs):
        child = structure.copy()
        child.translate_sites([1], [0.05, 0, 0], frac_coords=True)
        return BackendStructure(child, dict(kwargs))


class InterfaceBackend:
    def generate(self, inputs, **kwargs):
        child = Structure(
            Lattice.from_parameters(4, 4, 12, 90, 90, 90),
            ["Al", "Cu"],
            [[0, 0, 0.25], [0, 0, 0.7]],
        )
        return [BackendStructure(child, {"interface_area": 16.0, "mismatch": 0.0})]


def test_all_extended_generators_are_hash_deterministic():
    from llm_matgen.generators.dislocation import DislocationGenerator, DislocationParams
    from llm_matgen.generators.grain_boundary import GrainBoundaryGenerator, GrainBoundaryParams
    from llm_matgen.generators.interface import InterfaceGenerator, InterfaceInput, InterfaceParams
    from llm_matgen.generators.stacking_fault import StackingFaultGenerator, StackingFaultParams
    from llm_matgen.generators.surface import SurfaceGenerator, SurfaceParams

    cases = [
        (
            SurfaceGenerator(),
            source(),
            SurfaceParams(miller_indices=[(0, 0, 1)], min_slab_size=4, min_vacuum_size=4),
        ),
        (
            GrainBoundaryGenerator(GrainBackend()),
            source(),
            GrainBoundaryParams(rotation_axis=(0, 0, 1), rotation_angles=[15]),
        ),
        (
            InterfaceGenerator(InterfaceBackend()),
            InterfaceInput(film=source(), substrate=Structure(Lattice.cubic(4), ["Cu"], [[0, 0, 0]])),
            InterfaceParams(
                film_millers=[(0, 0, 1)], substrate_millers=[(0, 0, 1)],
                film_thickness=4, substrate_thickness=4, vacuum_thickness=4, gap=2,
                max_area=100, max_area_ratio_tol=0.1, max_length_tol=0.05, max_angle_tol=0.02,
            ),
        ),
        (
            StackingFaultGenerator(),
            source(),
            StackingFaultParams(plane=(0, 0, 1), slip_vector=(0.1, 0, 0)),
        ),
        (
            DislocationGenerator(),
            source(),
            DislocationParams(
                line_direction=(0, 0, 1), burgers_vector=(0, 0, 1), slip_plane=(1, 0, 0),
                character="screw", core_position=(0.5, 0.5), radius=5, poisson_ratio=0.3,
            ),
        ),
    ]
    for generator, inputs, params in cases:
        first = [item.record.structure_id for item in generator.generate(inputs, params).generated]
        second = [item.record.structure_id for item in generator.generate(inputs, params).generated]
        assert first == second
