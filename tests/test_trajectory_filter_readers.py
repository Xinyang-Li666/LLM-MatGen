from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class FilterReaderTests(unittest.TestCase):
    def test_lammps_triclinic_and_partial_pbc(self):
        from llm_matgen.trajectories.filtering.readers import FilterTrajectoryReader

        content = """ITEM: TIMESTEP
0
ITEM: NUMBER OF ATOMS
2
ITEM: BOX BOUNDS xy xz yz pp pp ff
0 10 1.0
0 10 0.5
0 10 0.2
ITEM: ATOMS id type xs ys zs fx fy fz
1 1 0.00 0.00 0.00 0.0 0.0 0.0
2 2 0.20 0.00 0.00 0.1 0.0 0.0
"""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "frame.dump"
            path.write_text(content, encoding="utf-8")
            frames = list(FilterTrajectoryReader(path, lammps_type_map={1: 22, 2: 5}).iter_frames())

        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].natoms, 2)
        self.assertEqual(frames[0].pbc.tolist(), [True, True, False])
        self.assertIsNotNone(frames[0].forces)
        self.assertTrue((abs(frames[0].cell - frames[0].cell.T) > 1e-12).any())

    def test_reader_is_streaming(self):
        from llm_matgen.trajectories.filtering.readers import FilterTrajectoryReader

        content = """2
Lattice="5 0 0 0 5 0 0 0 5" Properties=species:S:1:pos:R:3:Z:I:1
Ti 0 0 0 22
B 2 0 0 5
"""
        with TemporaryDirectory() as directory:
            path = Path(directory) / "frames.extxyz"
            path.write_text(content, encoding="utf-8")
            reader = FilterTrajectoryReader(path)
            iterator = reader.iter_frames()
            self.assertEqual(next(iterator).source_index, 0)
            iterator.close()


if __name__ == "__main__":
    unittest.main()
