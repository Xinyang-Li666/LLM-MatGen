from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np


def make_frame(index: int, close: bool = False):
    from llm_matgen.trajectories.filtering.models import FilterFrame

    return FilterFrame(
        atomic_numbers=np.array([22, 5]),
        positions=np.array([[0, 0, 0], [0.4 if close else 2.0, 0, 0]], dtype=float),
        cell=np.eye(3) * 10,
        pbc=np.array([True, True, True]), source_index=index, timestep=index * 10,
    )


class ProfileTests(unittest.TestCase):
    def test_profile_is_reproducible_and_serializable(self):
        from llm_matgen.trajectories.filtering.config import FilterConfig
        from llm_matgen.trajectories.filtering.profiles import calibrate_profile

        frames = [make_frame(index) for index in range(5)]
        profile = calibrate_profile(lambda: iter(frames), FilterConfig(checks=("coordination",), sample_count=3))
        encoded = json.dumps(profile.to_dict())
        self.assertIn("schema_version", encoded)
        self.assertEqual(profile.sample_indices, (0, 2, 4))


class EngineTests(unittest.TestCase):
    def test_engine_streams_and_counts_multiple_reasons(self):
        from llm_matgen.trajectories.filtering.config import FilterConfig
        from llm_matgen.trajectories.filtering.engine import FilterEngine

        frames = [make_frame(0), make_frame(1, close=True)]
        with TemporaryDirectory() as directory:
            result = FilterEngine(FilterConfig(checks=("overlap",))).run(
                lambda: iter(frames), Path(directory)
            )
            self.assertEqual(result.total, 2)
            self.assertEqual(result.anomalous, 1)
            self.assertEqual(len(result.review_path.read_text(encoding="utf-8").splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
