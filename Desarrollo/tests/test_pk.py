from __future__ import annotations

import sys
from pathlib import Path
import unittest

import geopandas as gpd
from shapely.geometry import LineString, Point

ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(ROOT))

from src.tramo import _m_values, extraer_tramo
from src.utils import format_pk


class TestPK(unittest.TestCase):
    def test_m_from_m_to_are_metres_even_when_values_are_small(self) -> None:
        gdf = gpd.GeoDataFrame(
            [{"m_from": 0, "m_to": 1500, "geometry": LineString([(0, 0), (1500, 0)])}],
            geometry="geometry",
            crs="EPSG:25830",
        )
        _m0, _m1, scale = _m_values(gdf, {"m_inicio": "m_from", "m_fin": "m_to"})
        self.assertEqual(scale, 1.0)

    def test_pk_fields_are_kilometres_even_when_values_are_small(self) -> None:
        gdf = gpd.GeoDataFrame(
            [{"pk_inicio": 0, "pk_fin": 2, "geometry": LineString([(0, 0), (2000, 0)])}],
            geometry="geometry",
            crs="EPSG:25830",
        )
        _m0, _m1, scale = _m_values(gdf, {"m_inicio": "pk_inicio", "m_fin": "pk_fin"})
        self.assertEqual(scale, 1000.0)

    def test_format_pk(self) -> None:
        self.assertEqual(format_pk(1), "1+000")
        self.assertEqual(format_pk(1.25), "1+250")
        self.assertEqual(format_pk(5.9996), "6+000")

    def test_extract_increasing(self) -> None:
        gdf = gpd.GeoDataFrame(
            [
                {"ID_ROAD": "A-1", "Via_sentido": "A-1_s_1", "m_from": 0, "m_to": 1000, "geometry": LineString([(0, 0), (1000, 0)])},
                {"ID_ROAD": "A-1", "Via_sentido": "A-1_s_1", "m_from": 1000, "m_to": 2000, "geometry": LineString([(1000, 0), (2000, 0)])},
            ],
            geometry="geometry",
            crs="EPSG:25830",
        )
        pks = gpd.GeoDataFrame(
            [{"MATRICULA": "A-1", "VALORKM": 0, "LABEL": "0+000", "geometry": Point(0, 0)}],
            geometry="geometry",
            crs="EPSG:25830",
        )
        cols = {"carretera": "ID_ROAD", "sentido": "Via_sentido", "m_inicio": "m_from", "m_fin": "m_to", "tipo_via": None}
        pk_cols = {"carretera": "MATRICULA", "sentido": None, "pk": "VALORKM", "label": "LABEL", "z": None}
        tramo = extraer_tramo(gdf, cols, "A-1", 0.5, 1.5, "creciente", pks, pk_cols)
        self.assertAlmostEqual(tramo.longitud_m, 1000, delta=1)
        self.assertEqual(tramo.pk_inicio_recorrido, 0.5)
        self.assertEqual(tramo.pk_fin_recorrido, 1.5)

    def test_extract_decreasing_normalizes(self) -> None:
        gdf = gpd.GeoDataFrame(
            [{"ID_ROAD": "A-1", "Via_sentido": "A-1_s_2", "m_from": 0, "m_to": 2000, "geometry": LineString([(0, 0), (2000, 0)])}],
            geometry="geometry",
            crs="EPSG:25830",
        )
        cols = {"carretera": "ID_ROAD", "sentido": "Via_sentido", "m_inicio": "m_from", "m_fin": "m_to", "tipo_via": None}
        tramo = extraer_tramo(gdf, cols, "A-1", 0.5, 1.5, "decreciente")
        self.assertEqual(tramo.pk_inicio_recorrido, 1.5)
        self.assertEqual(tramo.pk_fin_recorrido, 0.5)


if __name__ == "__main__":
    unittest.main()
