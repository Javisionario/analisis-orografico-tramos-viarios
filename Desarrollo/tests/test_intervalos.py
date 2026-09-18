from __future__ import annotations

import sys
from pathlib import Path
import unittest

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString

ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(ROOT))

from src.estilos import ELEVATION_STEPS, nice_elevation_classes, nice_elevation_classes_with_metadata
from src.mapas import _pk_items
from src.pendientes import segmentar_pendientes
from src.tramo import TramoExtraido
from src.utils import load_config


class TestIntervalos(unittest.TestCase):
    def test_elevation_classes_are_nice(self) -> None:
        classes = nice_elevation_classes(0, 500, 6)
        self.assertLessEqual(len(classes), 6)
        self.assertEqual(classes[0]["min"], 0)
        self.assertGreaterEqual(classes[-1]["max"], 500)

    def test_elevation_classes_do_not_start_at_zero_in_mountains(self) -> None:
        classes, meta = nice_elevation_classes_with_metadata(zmin=1030, zmax=2460, max_classes=6)
        self.assertGreaterEqual(classes[0]["min"], 1000)
        self.assertLessEqual(classes[-1]["max"], 2500)
        self.assertNotEqual(classes[0]["min"], 0)
        self.assertIn(meta["elevaciones_step_clase"], ELEVATION_STEPS)
        self.assertLessEqual(len(classes), 6)

    def test_elevation_classes_use_round_breaks_for_medium_range(self) -> None:
        classes, meta = nice_elevation_classes_with_metadata(zmin=1120, zmax=1780, max_classes=6)
        step = meta["elevaciones_step_clase"]
        self.assertIn(step, ELEVATION_STEPS)
        self.assertLessEqual(len(classes), 6)
        self.assertEqual(classes[0]["min"] % step, 0)
        self.assertEqual(classes[-1]["max"] % step, 0)

    def test_elevation_classes_can_start_at_zero_for_low_areas(self) -> None:
        classes, meta = nice_elevation_classes_with_metadata(zmin=0, zmax=180, max_classes=6)
        self.assertEqual(classes[0]["min"], 0)
        self.assertIn(meta["elevaciones_step_clase"], ELEVATION_STEPS)
        self.assertLessEqual(len(classes), 6)

    def test_elevation_classes_ignore_sparse_spurious_zeros(self) -> None:
        values = [0.0] + [1000.0 + i * (1460.0 / 98.0) for i in range(99)]
        classes, meta = nice_elevation_classes_with_metadata(values, max_classes=6)
        self.assertTrue(meta["elevaciones_ceros_ignorados_para_clasificacion"])
        self.assertGreaterEqual(classes[0]["min"], 1000)
        self.assertNotEqual(classes[0]["min"], 0)

    def test_slope_segmentation(self) -> None:
        geom = LineString([(0, 0), (1000, 0)])
        tramo = TramoExtraido(
            carretera="A-1",
            sentido="creciente",
            pk_inicio_usuario=0,
            pk_fin_usuario=1,
            pk_inicio_recorrido=0,
            pk_fin_recorrido=1,
            pk_min=0,
            pk_max=1,
            longitud_m=1000,
            geometry=geom,
            crs="EPSG:25830",
            advertencias=[],
            metadatos={},
        )
        perfil = pd.DataFrame(
            {
                "distancia_m": [0, 500, 1000],
                "pk": [0, 0.5, 1],
                "cota_suavizada_m": [100, 125, 150],
            }
        )
        config = load_config()
        segmentos, meta = segmentar_pendientes(tramo, perfil, 500, config)
        self.assertEqual(len(segmentos), 2)
        self.assertAlmostEqual(float(segmentos.iloc[0]["pendiente_pct"]), 5.0, places=3)
        self.assertEqual(meta["longitud_segmento_m"], 500)

    def test_slope_segmentation_uses_represented_profile_slope(self) -> None:
        geom = LineString([(0, 0), (1000, 0)])
        tramo = TramoExtraido(
            carretera="A-1",
            sentido="creciente",
            pk_inicio_usuario=0,
            pk_fin_usuario=1,
            pk_inicio_recorrido=0,
            pk_fin_recorrido=1,
            pk_min=0,
            pk_max=1,
            longitud_m=1000,
            geometry=geom,
            crs="EPSG:25830",
            advertencias=[],
            metadatos={},
        )
        perfil = pd.DataFrame(
            {
                "distancia_m": [0, 500, 1000],
                "pk": [0, 0.5, 1],
                "cota_suavizada_m": [100, 100, 100],
                "pendiente_bruta_pct": [18, 18, 18],
                "pendiente_suavizada_pct": [12, 12, 12],
                "pendiente_representada_pct": [0, 0, 0],
                "pendiente_anomala": [True, True, True],
            }
        )
        config = load_config()
        segmentos, meta = segmentar_pendientes(tramo, perfil, 500, config, 10)
        self.assertAlmostEqual(float(segmentos.iloc[0]["pendiente_pct"]), 0.0, places=3)
        self.assertAlmostEqual(float(segmentos.iloc[0]["pendiente_cota_segmento_pct"]), 0.0, places=3)
        self.assertEqual(perfil["pendiente_bruta_pct"].to_list(), [18, 18, 18])
        self.assertEqual(perfil["pendiente_suavizada_pct"].to_list(), [12, 12, 12])
        self.assertTrue(bool(segmentos.iloc[0]["pendiente_anomala"]))
        self.assertEqual(segmentos.iloc[0]["color"], "#ffff00")
        self.assertTrue(meta["pendiente_mapa_usa_suavizado_pendientes"])
        self.assertTrue(meta["pendiente_mapa_usa_aplanamiento"])

    def test_pk_items_uses_map_bounds_not_study_pk_range(self) -> None:
        tramo = TramoExtraido(
            carretera="A-1",
            sentido="creciente",
            pk_inicio_usuario=10,
            pk_fin_usuario=25,
            pk_inicio_recorrido=10,
            pk_fin_recorrido=25,
            pk_min=10,
            pk_max=25,
            longitud_m=15000,
            geometry=LineString([(0, 0), (1, 0)]),
            crs="EPSG:4326",
            advertencias=[],
            metadatos={},
        )
        pks = gpd.GeoDataFrame(
            {
                "carretera": ["A-1", "A-1", "A-1", "A-2", "A-1"],
                "pk": [9, 10, 25, 18, 26],
                "etiqueta": ["9+000", "10+000", "25+000", "18+000", "26+000"],
            },
            geometry=gpd.points_from_xy([0.10, 0.20, 0.80, 0.60, 1.10], [0.50, 0.50, 0.50, 0.50, 0.50]),
            crs="EPSG:4326",
        )
        items = _pk_items(
            pks,
            {"carretera": "carretera", "pk": "pk", "label": "etiqueta"},
            tramo,
            (0.0, 0.0, 1.0, 1.0),
            {
                "mostrar_simbolos": True,
                "simbolo_cada_pk": 1,
                "etiqueta_cada_pk": 5,
            },
        )
        self.assertEqual([item["km"] for item in items], [9.0, 10.0, 25.0])
        self.assertEqual([item["mostrar_etiqueta"] for item in items], [False, True, True])


if __name__ == "__main__":
    unittest.main()
