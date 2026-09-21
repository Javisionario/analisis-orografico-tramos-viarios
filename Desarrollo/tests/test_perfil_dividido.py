from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(ROOT))

from src.estilos import DIVISION_INTERIOR_PALETTE  # noqa: E402
from src.mapas import DIVISION_INTERIOR_PALETTE as MAP_PALETTE  # noqa: E402
from src.perfil_grafico import PROFILE_DIVISION_FILL_PALETTE, distance_at_pk, division_fill_arrays, exportar_perfil  # noqa: E402
from src.subtramos import DIVISION_COLORS  # noqa: E402
from src.tramo import TramoExtraido  # noqa: E402


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

    def test_export_uses_physical_distance_for_curve_and_pk_ticks(self) -> None:
        tramo = TramoExtraido(
            "A-1", "creciente", 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 225.0,
            LineString([(0, 0), (225, 0)]), "EPSG:25830", [], {}, [(0.0, 0.0), (100.0, 900.0), (225.0, 1000.0)],
        )
        profile = pd.DataFrame({
            "distancia_m": [0.0, 100.0, 225.0], "pk": [0.0, 0.9, 1.0],
            "cota_suavizada_m": [10.0, 15.0, 20.0], "cota_bruta_m": [10.0, 15.0, 20.0],
        })
        plotted: list[np.ndarray] = []
        ticks: list[np.ndarray] = []
        original_plot, original_ticks = Axes.plot, Axes.set_xticks

        def record_plot(axis: Axes, values: object, *args: object, **kwargs: object) -> object:
            plotted.append(np.asarray(values, dtype=float))
            return original_plot(axis, values, *args, **kwargs)

        def record_ticks(axis: Axes, values: object, *args: object, **kwargs: object) -> object:
            ticks.append(np.asarray(values, dtype=float))
            return original_ticks(axis, values, *args, **kwargs)

        with patch.object(Axes, "plot", record_plot), patch.object(Axes, "set_xticks", record_ticks), patch.object(Figure, "savefig"):
            exportar_perfil(profile, Path("perfil"), False, tramo)

        np.testing.assert_array_equal(plotted[0], np.array([0.0, 100.0, 225.0]))
        self.assertTrue(any(np.isclose(values, 55.5555555556).any() for values in ticks))


if __name__ == "__main__":
    unittest.main()
