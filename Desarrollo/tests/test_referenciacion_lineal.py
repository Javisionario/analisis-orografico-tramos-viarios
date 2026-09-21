from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from shapely import to_wkb
from shapely.geometry import LineString, MultiLineString, Point

ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(ROOT))

from src.referenciacion_lineal import component_coordinates, distance_at_m, extract_between_m_with_calibration, m_at_distance, m_at_point, measured_parts_from_gpkg, point_at_m, row_coords  # noqa: E402
from src.tramo import extraer_tramo  # noqa: E402
from src.tramo import TramoExtraido  # noqa: E402
from src.perfiles import generar_perfil  # noqa: E402


class MeasuredLinearReferencingTests(unittest.TestCase):
    # M intentionally differs from the XY distance fraction at x=100.
    coords = [(0.0, 0.0, 0.0), (100.0, 0.0, 900.0), (1000.0, 0.0, 1000.0)]

    def test_xy_to_m_uses_local_vertex_segment(self) -> None:
        measured = m_at_point(self.coords, Point(100, 0))
        self.assertIsNotNone(measured)
        self.assertEqual(measured[0], 900.0)

    def test_m_to_xy_and_roundtrip(self) -> None:
        point = point_at_m(self.coords, 900)
        self.assertEqual((point.x, point.y), (100.0, 0.0))
        self.assertAlmostEqual(m_at_point(self.coords, point)[0], 900.0)

    def test_extracts_real_m_breakpoint_and_calibration(self) -> None:
        geometry, calibration = extract_between_m_with_calibration(self.coords, 0, 1000)
        self.assertEqual(list(geometry.coords)[1], (100.0, 0.0))
        self.assertEqual(m_at_distance(calibration, 100.0), 900.0)

    def test_decreasing_m_preserves_route_orientation(self) -> None:
        geometry, calibration = extract_between_m_with_calibration(self.coords, 1000, 0)
        self.assertEqual(tuple(geometry.coords[0]), (1000.0, 0.0))
        self.assertEqual(calibration[0][1], 1000.0)

    def test_fallback_is_explicit(self) -> None:
        row = {}; geometry = LineString([(0, 0), (100, 0)])
        _coords, method = row_coords(row, geometry, 0, 100)
        self.assertEqual(method, "row_bounds_xy_fallback")

    def test_multiline_components_keep_their_own_m_ranges(self) -> None:
        geometry = MultiLineString([[(0, 0), (100, 0)], [(100, 0), (200, 0)]])
        row = {"__m_parts": [[(0, 0, 0), (100, 0, 900)], [(100, 0, 900), (200, 0, 1000)]]}
        components = component_coordinates(row, geometry, 0, 1000)
        self.assertEqual(len(components), 2)
        self.assertEqual(components[0][1][-1][2], 900)
        self.assertEqual(components[1][1][0][2], 900)

    def test_tramo_keeps_multipart_geometry_and_internal_calibration_together(self) -> None:
        import geopandas as gpd

        geometry = MultiLineString([[(0, 0), (100, 0)], [(100, 0), (200, 0)]])
        data = gpd.GeoDataFrame(
            [{"ID_ROAD": "A", "Via_sentido": "A_s_1", "m_from": 0, "m_to": 1000,
              "__m_parts": [[(0, 0, 0), (100, 0, 900)], [(100, 0, 900), (200, 0, 1000)]], "geometry": geometry}],
            geometry="geometry", crs="EPSG:25830",
        )
        cols = {"carretera": "ID_ROAD", "sentido": "Via_sentido", "m_inicio": "m_from", "m_fin": "m_to", "tipo_via": None}
        tramo = extraer_tramo(data, cols, "A", 0.0, 1.0, "creciente")
        self.assertIsInstance(tramo.geometry, MultiLineString)
        self.assertNotIn("calibracion_distancia_m", tramo.metadatos)
        self.assertAlmostEqual(m_at_distance(tramo.calibracion_distancia_m, 100), 900)

    def test_tramo_selects_one_parallel_calibrated_carriageway(self) -> None:
        import geopandas as gpd

        source = gpd.GeoDataFrame([
            {"ID_ROAD": "A", "Via_sentido": "A_s_1", "m_from": 0, "m_to": 1000, "geometry": LineString([(0, 0), (1000, 0)])},
            {"ID_ROAD": "A", "Via_sentido": "A_s_1", "m_from": 0, "m_to": 1000, "geometry": LineString([(0, 50), (1000, 50)])},
        ], geometry="geometry", crs="EPSG:25830")
        cols = {"carretera": "ID_ROAD", "sentido": "Via_sentido", "m_inicio": "m_from", "m_fin": "m_to", "tipo_via": None}
        tramo = extraer_tramo(source, cols, "A", 0, 1, "creciente")
        self.assertIsInstance(tramo.geometry, LineString)
        self.assertAlmostEqual(tramo.longitud_m, 1000.0)
        self.assertEqual(len(tramo.calibracion_distancia_m), 2)

    def test_tramo_rejects_disconnected_contiguous_calibration(self) -> None:
        import geopandas as gpd

        source = gpd.GeoDataFrame([
            {"ID_ROAD": "A", "Via_sentido": "A_s_1", "m_from": 0, "m_to": 500, "geometry": LineString([(0, 0), (500, 0)])},
            {"ID_ROAD": "A", "Via_sentido": "A_s_1", "m_from": 500, "m_to": 1000, "geometry": LineString([(500, 50), (1000, 50)])},
        ], geometry="geometry", crs="EPSG:25830")
        cols = {"carretera": "ID_ROAD", "sentido": "Via_sentido", "m_inicio": "m_from", "m_fin": "m_to", "tipo_via": None}
        with self.assertRaisesRegex(ValueError, "físicamente discontinuas"):
            extraer_tramo(source, cols, "A", 0, 1, "creciente")

    def test_outside_calibration_is_not_silently_clamped(self) -> None:
        with self.assertRaises(ValueError):
            m_at_distance([(0, 0), (100, 100)], -0.1)

    def test_distance_at_m_uses_the_real_non_proportional_calibration(self) -> None:
        self.assertEqual(distance_at_m([(0, 0), (100, 900), (1000, 1000)], 900), 100)
        self.assertEqual(distance_at_m([(0, 1000), (900, 900), (1000, 0)], 900), 900)

    def test_z_only_wkb_is_not_misidentified_as_measured(self) -> None:
        wkb = to_wkb(LineString([(0, 0, 1), (10, 0, 2)]), output_dimension=3)
        gpkg_blob = b"GP\x00\x01\x00\x00\x00\x00" + wkb
        self.assertEqual(measured_parts_from_gpkg(gpkg_blob), [])

    def test_profile_pk_uses_piecewise_m_but_keeps_xy_distances(self) -> None:
        tramo = TramoExtraido(
            "A", "creciente", 0, 1, 0, 1, 0, 1, 1000,
            LineString([(0, 0), (100, 0), (1000, 0)]), "EPSG:25830", [], {},
            [(0, 0), (100, 900), (1000, 1000)],
        )
        profile, _meta, _warnings = generar_perfil(
            tramo, None, pd.DataFrame({"pk": np.linspace(0, 1, 101), "z": np.zeros(101)}),
            {"pk": "pk", "z": "z"}, 100, 0, halo_puntos=0,
        )
        self.assertEqual(float(profile.iloc[1]["distancia_m"]), 100.0)
        self.assertAlmostEqual(float(profile.iloc[1]["pk"]), 0.9)
        self.assertGreater(float(profile.iloc[2]["pk"]), 0.9)
        self.assertLess(float(profile.iloc[2]["pk"]), 0.93)

    def test_profile_halo_uses_calculation_tramo_calibration(self) -> None:
        calculation = TramoExtraido(
            "A", "creciente", 0, 1, 0, 1, 0, 1, 1000,
            LineString([(0, 0), (100, 0), (1000, 0)]), "EPSG:25830", [], {},
            [(0, 0), (100, 900), (1000, 1000)],
        )
        visible = TramoExtraido(
            "A", "creciente", .9, 1, .9, 1, .9, 1, 900,
            LineString([(100, 0), (1000, 0)]), "EPSG:25830", [], {},
            [(0, 900), (900, 1000)],
        )
        profile, _meta, _warnings = generar_perfil(
            visible, None, pd.DataFrame({"pk": np.linspace(0, 1, 101), "z": np.zeros(101)}),
            {"pk": "pk", "z": "z"}, 100, 0, tramo_calculo=calculation, halo_puntos=1,
        )
        self.assertAlmostEqual(float(profile.iloc[0]["pk"]), .9)

    def test_division_boundary_uses_its_real_m_position(self) -> None:
        import geopandas as gpd

        source = gpd.GeoDataFrame(
            [{"ID_ROAD": "A", "Via_sentido": "A_s_1", "m_from": 0, "m_to": 1000,
              "__m_parts": [self.coords], "geometry": LineString([(0, 0), (100, 0), (1000, 0)])}],
            geometry="geometry", crs="EPSG:25830",
        )
        cols = {"carretera": "ID_ROAD", "sentido": "Via_sentido", "m_inicio": "m_from", "m_fin": "m_to", "tipo_via": None}
        left = extraer_tramo(source, cols, "A", 0, .9, "creciente")
        right = extraer_tramo(source, cols, "A", .9, 1, "creciente")
        self.assertEqual(tuple(left.geometry.coords[-1]), (100.0, 0.0))
        self.assertEqual(tuple(right.geometry.coords[0]), (100.0, 0.0))
