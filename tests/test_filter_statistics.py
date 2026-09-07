from __future__ import annotations

import unittest

import numpy as np


class StatisticsDetectorTests(unittest.TestCase):
    def frame(self, forces=None):
        from llm_matgen.trajectories.filtering.models import FilterFrame

        return FilterFrame(
            atomic_numbers=np.array([22, 5, 5]),
            positions=np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0]], dtype=float),
            cell=np.eye(3) * 10, pbc=np.array([True, True, True]),
            forces=forces, source_index=0,
        )

    def test_force_without_data_is_not_evaluated(self):
        from llm_matgen.trajectories.filtering.force import check_force

        self.assertEqual(check_force(self.frame()).status, "not_evaluated")

    def test_force_threshold_is_applied(self):
        from llm_matgen.trajectories.filtering.force import check_force

        result = check_force(self.frame(np.array([[3, 0, 0], [0, 0, 0], [0, 0, 0.0]])), threshold=2.0)
        self.assertEqual(result.status, "fail")
        self.assertEqual(result.metrics["max_force"], 3.0)

    def test_coordination_uses_reference_bounds(self):
        from llm_matgen.trajectories.filtering.coordination import check_coordination

        result = check_coordination(
            self.frame(), bounds={"all": (0.0, 0.5)}, groups={"all": [5, 22]}, cutoff=2.5,
        )
        self.assertEqual(result.status, "fail")


if __name__ == "__main__":
    unittest.main()
