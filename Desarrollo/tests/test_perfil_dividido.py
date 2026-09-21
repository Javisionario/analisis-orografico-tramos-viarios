from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(ROOT))

from src.estilos import DIVISION_INTERIOR_PALETTE  # noqa: E402
from src.mapas import DIVISION_INTERIOR_PALETTE as MAP_PALETTE  # noqa: E402
from src.perfil_grafico import PROFILE_DIVISION_FILL_PALETTE, distance_at_pk, division_fill_arrays  # noqa: E402
from src.subtramos import DIVISION_COLORS  # noqa: E402


class DividedProfileTests(unittest.TestCase):
    def test_pk_tick_uses_measured_distance_not_global_fraction(self) -> None:
        distances = np.array([0.0, 100.0, 1000.0])
        pks = np.array([0.0, 0.9, 1.0])
        self.assertEqual(distance_at_pk(distances, pks, 0.9), 100.0)
        self.assertEqual(distance_at_pk(distances, np.array([1.0, 0.1, 0.0]), 0.1), 100.0)

    def test_fill_parts_share_an_interpolated_non_sample_boundary_without_gap(self) -> None:
        x = np.array([0.0, 75.0, 150.0, 225.0])
        z = np.array([10.0, 20.0, 40.0, 55.0])
        left_x, left_z = division_fill_arrays(x, z, 0.0, 110.0)
        right_x, right_z = division_fill_arrays(x, z, 110.0, 225.0)
        self.assertEqual(left_x[-1], 110.0)
        self.assertEqual(right_x[0], 110.0)
        self.assertEqual(left_z[-1], right_z[0])
        self.assertEqual(np.unique(np.concatenate((left_x, right_x))).tolist(), [0.0, 75.0, 110.0, 150.0, 225.0])

    def test_division_palettes_are_distinct_and_map_has_one_source(self) -> None:
        self.assertNotEqual(PROFILE_DIVISION_FILL_PALETTE[0], PROFILE_DIVISION_FILL_PALETTE[1])
        self.assertNotEqual(DIVISION_INTERIOR_PALETTE[0], DIVISION_INTERIOR_PALETTE[1])
        self.assertEqual(MAP_PALETTE, DIVISION_INTERIOR_PALETTE)
        self.assertEqual(DIVISION_COLORS, DIVISION_INTERIOR_PALETTE)


if __name__ == "__main__":
    unittest.main()
