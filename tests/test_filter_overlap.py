from __future__ import annotations

import unittest

import numpy as np


class OverlapDetectorTests(unittest.TestCase):
    def frame(self, positions, types=(22, 5), cell=None, pbc=(True, True, True)):
        from llm_matgen.trajectories.filtering.models import FilterFrame

        return FilterFrame(
            atomic_numbers=np.array(types), positions=np.asarray(positions, dtype=float),
            cell=np.eye(3) * 10 if cell is None else cell,
            pbc=np.array(pbc), source_index=0,
        )

    def test_close_pair_fails(self):
        from llm_matgen.trajectories.filtering.overlap import check_overlap

        result = check_overlap(self.frame([[0, 0, 0], [0.4, 0, 0]]))
        self.assertEqual(result.status, "fail")
        self.assertGreaterEqual(result.metrics["overlap_atoms"], 2)

    def test_periodic_boundary_pair_is_detected_in_triclinic_cell(self):
        from llm_matgen.trajectories.filtering.overlap import check_overlap

        cell = np.array([[5.0, 0.0, 0.0], [1.5, 5.0, 0.0], [0.5, 0.2, 5.0]])
        result = check_overlap(self.frame([[0, 0, 0], [4.9, 0, 0]], cell=cell))
        self.assertEqual(result.status, "fail")

    def test_custom_pair_threshold_is_used(self):
        from llm_matgen.trajectories.filtering.overlap import check_overlap

        frame = self.frame([[0, 0, 0], [1.0, 0, 0]])
        result = check_overlap(frame, pair_min_distance={(5, 22): 1.1}, overlap_ratio=0.0)
        self.assertEqual(result.status, "fail")


if __name__ == "__main__":
    unittest.main()
