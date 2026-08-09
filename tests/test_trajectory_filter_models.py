from __future__ import annotations

import unittest

import numpy as np


class FilterFrameTests(unittest.TestCase):
    def test_valid_frame_preserves_partial_pbc_and_metadata(self):
        from llm_matgen.trajectories.filtering.models import FilterFrame

        frame = FilterFrame(
            atomic_numbers=np.array([22, 5]),
            positions=np.array([[0.0, 0.0, 0.0], [2.0, 0.0, 0.0]]),
            cell=np.diag([5.0, 6.0, 7.0]),
            pbc=np.array([True, True, False]),
            forces=None,
            source_index=3,
            timestep=100,
            metadata={"temperature": 300.0},
        )

        self.assertEqual(frame.natoms, 2)
        np.testing.assert_array_equal(frame.pbc, [True, True, False])
        self.assertEqual(frame.metadata["temperature"], 300.0)

    def test_invalid_numeric_values_reach_numeric_detector(self):
        from llm_matgen.trajectories.filtering.models import FilterFrame
        from llm_matgen.trajectories.filtering.numeric import check_frame

        frame = FilterFrame(
            atomic_numbers=np.array([22]),
            positions=np.array([[np.nan, 0.0, 0.0]]),
            cell=np.eye(3),
            pbc=np.array([True, True, True]),
            forces=None,
            source_index=0,
        )
        result = check_frame(frame)
        self.assertEqual(result.status, "fail")
        self.assertIn("non_finite_positions", result.reasons)


if __name__ == "__main__":
    unittest.main()
