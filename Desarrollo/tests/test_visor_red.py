from __future__ import annotations

import sys
import unittest
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point

ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(ROOT))

from src.visor_red import bbox_wgs84_a_crs, localizar_pk, medir, punto_a_pk  # noqa: E402


COLS = {
    "carretera": "ID_ROAD",
    "sentido": "Via_sentido",
    "m_inicio": "m_from",
    "m_fin": "m_to",
    "tipo_via": "Tipo_via",
}


def lines(rows: list[dict]) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:25830")


class VisorRedTests(unittest.TestCase):
    def test_pk_to_point_interpolates_calibrated_segment(self) -> None:
        data = lines([{"ID_ROAD": "A-1", "Via_sentido": "A-1_s_1", "m_from": 10000, "m_to": 11000, "geometry": LineString([(0, 0), (1000, 0)])}])
        point = localizar_pk(data, COLS, "A-1", 10.5)
        self.assertAlmostEqual(point.snapped.x, 500, delta=0.01)

    def test_point_to_pk_respects_reverse_calibration(self) -> None:
        data = lines([{"ID_ROAD": "A-1", "Via_sentido": "A-1_s_1", "m_from": 11000, "m_to": 10000, "geometry": LineString([(0, 0), (1000, 0)])}])
        candidates = punto_a_pk(data, COLS, Point(250, 5), 10)
        self.assertEqual(len(candidates), 1)
        self.assertAlmostEqual(candidates[0].pk, 10.75, delta=0.001)

    def test_point_outside_tolerance_is_not_accepted(self) -> None:
        data = lines([{"ID_ROAD": "A-1", "Via_sentido": "A-1_s_1", "m_from": 0, "m_to": 1000, "geometry": LineString([(0, 0), (1000, 0)])}])
        self.assertEqual(punto_a_pk(data, COLS, Point(500, 30), 20), [])

    def test_measurement_resolves_common_road(self) -> None:
        data = lines([
            {"ID_ROAD": "A", "Via_sentido": "A_s_1", "m_from": 0, "m_to": 3000, "geometry": LineString([(0, 0), (3000, 0)])},
            {"ID_ROAD": "B", "Via_sentido": "B_s_1", "m_from": 0, "m_to": 1000, "geometry": LineString([(0, 0), (1000, 0)])},
        ])
        result = medir(data, COLS, Point(500, 0), Point(2000, 0), 20)
        self.assertEqual(result["estado"], "ok")
        self.assertEqual(result["carretera"], "A")

    def test_measurement_reports_persistent_ambiguity(self) -> None:
        data = lines([
            {"ID_ROAD": "A", "Via_sentido": "A_s_1", "m_from": 0, "m_to": 1000, "geometry": LineString([(0, 0), (1000, 0)])},
            {"ID_ROAD": "B", "Via_sentido": "B_s_1", "m_from": 0, "m_to": 1000, "geometry": LineString([(0, 0), (1000, 0)])},
        ])
        result = medir(data, COLS, Point(100, 0), Point(900, 0), 20)
        self.assertEqual(result["estado"], "ambiguo")
        self.assertEqual(result["carreteras"], ["A", "B"])

    def test_measurement_rejects_incompatible_roads(self) -> None:
        data = lines([
            {"ID_ROAD": "A", "Via_sentido": "A_s_1", "m_from": 0, "m_to": 1000, "geometry": LineString([(0, 0), (1000, 0)])},
            {"ID_ROAD": "B", "Via_sentido": "B_s_1", "m_from": 0, "m_to": 1000, "geometry": LineString([(0, 100), (1000, 100)])},
        ])
        result = medir(data, COLS, Point(100, 0), Point(900, 100), 20)
        self.assertEqual(result["estado"], "incompatible")

    def test_distance_follows_geometry_not_pk_delta(self) -> None:
        data = lines([{"ID_ROAD": "A", "Via_sentido": "A_s_1", "m_from": 0, "m_to": 1000, "geometry": LineString([(0, 0), (500, 500), (1000, 0)])}])
        result = medir(data, COLS, Point(0, 0), Point(1000, 0), 20)
        self.assertEqual(result["estado"], "ok")
        self.assertAlmostEqual(result["diferencia_pk_m"], 1000, delta=0.01)
        self.assertAlmostEqual(result["distancia_geometria_m"], 1414.21356, delta=0.1)
        self.assertNotAlmostEqual(result["distancia_geometria_m"], result["diferencia_pk_m"], delta=1)

    def test_parallel_carriageways_are_not_summed(self) -> None:
        data = lines([
            {"ID_ROAD": "A", "Via_sentido": "A_s_1", "m_from": 0, "m_to": 1000, "geometry": LineString([(0, 0), (1000, 0)])},
            {"ID_ROAD": "A", "Via_sentido": "A_s_2", "m_from": 0, "m_to": 1000, "geometry": LineString([(0, 50), (1000, 50)])},
        ])
        result = medir(data, COLS, Point(0, 0), Point(1000, 0), 20)
        self.assertEqual(result["estado"], "ok")
        self.assertAlmostEqual(result["distancia_geometria_m"], 1000, delta=0.01)

    def test_measurement_crosses_contiguous_idvia_change_in_the_same_direction(self) -> None:
        data = lines([
            {"ID_ROAD": "A", "IDVIA": "first", "Via_sentido": "A_s_1", "m_from": 662000, "m_to": 662898, "geometry": LineString([(0, 0), (898, 0)])},
            {"ID_ROAD": "A", "IDVIA": "second", "Via_sentido": "A_s_1", "m_from": 662898, "m_to": 664000, "geometry": LineString([(898, 0), (2000, 0)])},
        ])
        result = medir(data, COLS, Point(800, 0), Point(1000, 0), 20)
        self.assertEqual(result["estado"], "ok")
        self.assertAlmostEqual(result["distancia_geometria_m"], 200, delta=0.01)

    def test_measurement_rejects_disconnected_calibrated_branch(self) -> None:
        data = lines([
            {"ID_ROAD": "A", "Via_sentido": "A_s_1", "m_from": 0, "m_to": 1000, "geometry": LineString([(0, 0), (1000, 0)])},
            {"ID_ROAD": "A", "Via_sentido": "A_s_1", "m_from": 1000, "m_to": 2000, "geometry": LineString([(2000, 0), (3000, 0)])},
        ])
        result = medir(data, COLS, Point(0, 0), Point(3000, 0), 20)
        self.assertEqual(result["estado"], "incompatible")

    def test_leaflet_fallback_keeps_result_return_action_registered(self) -> None:
        script = (ROOT / "static" / "js" / "road_viewer.js").read_text(encoding="utf-8")
        self.assertLess(
            script.index('resultsButton.addEventListener("click"'),
            script.index("if (!window.L || !mapElement)"),
        )

    def test_bbox_wgs84_is_transformed_to_layer_crs(self) -> None:
        west, south, east, north = bbox_wgs84_a_crs((-3.70, 40.40, -3.60, 40.50), "EPSG:25830")
        self.assertLess(west, east)
        self.assertLess(south, north)
        self.assertGreater(west, 400000)
        self.assertLess(east, 500000)


if __name__ == "__main__":
    unittest.main()
