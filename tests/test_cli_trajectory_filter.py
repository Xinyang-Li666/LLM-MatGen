from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class TrajectoryFilterCliTests(unittest.TestCase):
    def test_new_filter_options_parse(self):
        from llm_matgen.__main__ import build_parser

        args = build_parser().parse_args([
            "filter", "trajectory", "input.dump",
            "--checks", "overlap", "force",
            "--threshold-profile", "profile.json",
            "--output-format", "extxyz",
            "--assume-type-is-z", "--strict",
        ])
        self.assertEqual(args.checks, ["overlap", "force"])
        self.assertTrue(args.assume_type_is_z)
        self.assertTrue(args.strict)

    def test_default_filter_check_is_overlap_only(self):
        from llm_matgen.__main__ import build_parser

        args = build_parser().parse_args(["filter", "trajectory", "input.dump"])
        self.assertIsNone(args.checks)
        self.assertIsNone(args.dimensions)

    def test_cli_runs_lammps_filter_and_emits_summary(self):
        from llm_matgen.__main__ import main

        content = """ITEM: TIMESTEP
0
ITEM: NUMBER OF ATOMS
2
ITEM: BOX BOUNDS pp pp pp
0 10
0 10
0 10
ITEM: ATOMS id type x y z
1 1 0 0 0
2 2 2 0 0
"""
        with TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            input_path = root / "input.dump"
            output_root = root / "output"
            input_path.write_text(content, encoding="utf-8")
            code = main([
                "filter", "trajectory", str(input_path),
                "--lammps-element", "1=Ti", "--lammps-element", "2=B",
                "--output-root", str(output_root),
            ])
            self.assertEqual(code, 0)
            run_dirs = list(output_root.iterdir())
            self.assertEqual(len(run_dirs), 1)
            self.assertTrue((run_dirs[0] / "summary.json").exists())


if __name__ == "__main__":
    unittest.main()
