from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np


class WriterSafetyTests(unittest.TestCase):
    def test_run_directory_is_unique_and_summary_is_json(self):
        from llm_matgen.trajectories.filtering.config import FilterConfig
        from llm_matgen.trajectories.filtering.engine import FilterEngine
        from llm_matgen.trajectories.filtering.models import FilterFrame

        frame = FilterFrame(
            atomic_numbers=np.array([6, 6]), positions=np.array([[0, 0, 0], [2, 0, 0]], float),
            cell=np.eye(3) * 10, pbc=np.array([True, True, True]), source_index=0,
        )
        with TemporaryDirectory() as directory:
            result = FilterEngine(FilterConfig(checks=("overlap",))).run(lambda: iter([frame]), Path(directory))
            summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["total"], 1)
            self.assertTrue(result.clean_path.exists())
            self.assertTrue(result.anomalous_path.exists())


if __name__ == "__main__":
    unittest.main()
