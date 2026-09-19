from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import pyogrio
from shapely.geometry import LineString, Point

ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(ROOT))

import app as web_app  # noqa: E402
from src.io_datos import detect_columns  # noqa: E402
from src.visor_pks import csv_text, export_rows, parse_pk_text, pk_bbox_items, write_gpkg  # noqa: E402


PK_COLS = {"carretera": "MATRICULA", "pk": "VALORKM", "rotacion": "rotacion"}


class ViewerPkTests(unittest.TestCase):
    def test_rotation_column_is_detected_from_configured_candidates(self) -> None:
        data = gpd.GeoDataFrame({"MATRICULA": ["A-1"], "VALORKM": [1], "rotacion": [90]}, geometry=[Point(0, 0)], crs="EPSG:25830")
        config = {"campos": {"carretera_pks": ["MATRICULA"], "pk_punto": ["VALORKM"], "rotacion_pks": ["rot", "rotacion"]}}
        self.assertEqual(detect_columns(data, config, pk=True)["rotacion"], "rotacion")

    def test_bbox_items_filter_roads_and_intervals(self) -> None:
        pks = gpd.GeoDataFrame({"MATRICULA": ["A-1", "A-1", "M-11"], "VALORKM": [5, 6, 10], "rotacion": [0, 0, 0]}, geometry=[Point(0, 0), Point(1000, 0), Point(2000, 0)], crs="EPSG:25830")
        lines = gpd.GeoDataFrame(geometry=[LineString([(0, 0), (2500, 0)])], crs="EPSG:25830")
        only_a1 = pk_bbox_items(pks, PK_COLS, lines, ["A-1"], 5)
        self.assertEqual([(item["carretera"], item["pk"]) for item in only_a1], [("A-1", 5.0)])
        both = pk_bbox_items(pks, PK_COLS, lines, ["A-1", "M-11"], 5)
        self.assertEqual([item["pk"] for item in both], [5.0, 10.0])
        self.assertEqual(pk_bbox_items(pks, PK_COLS, lines, ["A-1"], 1)[1]["pk"], 6.0)

    def test_text_parser_accepts_requested_separators_and_keeps_errors(self) -> None:
        points, errors = parse_pk_text("N-320 160+000\nA-1; 250+000\nM-11, 4,500\nXXX texto inválido")
        self.assertEqual([(item["carretera"], item["pk"]) for item in points], [("N-320", 160.0), ("A-1", 250.0), ("M-11", 4.5)])
        self.assertEqual(len(errors), 1)

    def test_csv_and_gpkg_have_requested_schema(self) -> None:
        rows = export_rows([{"carretera": "A-1", "pk": 25, "longitud": -3.7, "latitud": 40.4}])
        self.assertEqual(csv_text(rows).splitlines()[0], "carretera,pk,pk_numerico,longitud,latitud")
        handle = tempfile.NamedTemporaryFile(dir=ROOT, suffix=".gpkg", delete=False)
        target = Path(handle.name)
        handle.close()
        target.unlink()
        try:
            write_gpkg(rows, target)
            info = pyogrio.read_info(target, layer="pks")
            data = gpd.read_file(target, layer="pks")
        finally:
            target.unlink(missing_ok=True)
        self.assertEqual(info["layer_name"], "pks")
        self.assertEqual(str(data.crs), "EPSG:4326")
        self.assertEqual(list(data.drop(columns="geometry").columns), ["carretera", "pk", "pk_numerico", "longitud", "latitud"])

    def test_batch_groups_each_resolved_road_once_and_returns_partial_errors(self) -> None:
        payload = web_app.LocalizarPksRequest(puntos=[{"carretera": "A-1", "pk": 1}, {"carretera": "A 1", "pk": 2}, {"carretera": "NO", "pk": 1}])
        with patch.object(web_app, "load_config", return_value={}), patch.object(web_app, "resolve_road_name", side_effect=lambda _c, road: "A-1" if road != "NO" else None), patch.object(web_app, "load_lineas", return_value=(gpd.GeoDataFrame({"ID_ROAD": ["A-1"], "m_from": [0], "m_to": [3000], "Via_sentido": ["A_s_1"]}, geometry=[LineString([(0, 0), (3000, 0)])], crs="EPSG:25830"), {"carretera": "ID_ROAD", "m_inicio": "m_from", "m_fin": "m_to", "sentido": "Via_sentido"}, [])) as load:
            response = web_app.visor_localizar_pks(payload)
        self.assertEqual(load.call_count, 1)
        self.assertEqual([item["indice"] for item in response["resultados"]], [0, 1, 2])
        self.assertIn("error", response["resultados"][2])


if __name__ == "__main__":
    unittest.main()
