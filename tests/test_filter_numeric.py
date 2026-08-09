from __future__ import annotations

import unittest

import numpy as np


def make_frame(types=(22, 5), cell=None, pbc=(True, True, True), positions=None):
    from llm_matgen.trajectories.filtering.models import FilterFrame

    if positions is None:
        positions = np.array([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]])
    return FilterFrame(
        atomic_numbers=np.array(types), positions=positions,
        cell=np.eye(3) * 10 if cell is None else cell,
        pbc=np.array(pbc), source_index=0,
    )


class NumericDetectorTests(unittest.TestCase):
    def test_valid_frame_passes(self):
        from llm_matgen.trajectories.filtering.numeric import check_frame

        result = check_frame(make_frame())
        self.assertEqual(result.status, "pass")

    def test_nonperiodic_frame_without_cell_passes(self):
        from llm_matgen.trajectories.filtering.models import FilterFrame
        from llm_matgen.trajectories.filtering.numeric import check_frame

        frame = FilterFrame(
            atomic_numbers=np.array([6, 6]),
            positions=np.array([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]]),
            cell=None, pbc=np.array([False, False, False]), source_index=0,
        )
        self.assertEqual(check_frame(frame).status, "pass")

    def test_composition_change_is_reported(self):
        from llm_matgen.trajectories.filtering.numeric import check_frame

        result = check_frame(make_frame(types=(22, 8)), reference_numbers=np.array([22, 5]))
        self.assertEqual(result.status, "fail")
        self.assertIn("composition_changed", result.reasons)


class CellDetectorTests(unittest.TestCase):
    def test_volume_change_is_optional(self):
        from llm_matgen.trajectories.filtering.cell import check_cell

        frame = make_frame(cell=np.diag([12.0, 10.0, 10.0]))
        result = check_cell(frame, reference_volume=100.0, max_volume_change=0.05)
        self.assertEqual(result.status, "fail")
        self.assertIn("cell_volume_change", result.reasons)


if __name__ == "__main__":
    unittest.main()
