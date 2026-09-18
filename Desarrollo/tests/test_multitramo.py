from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from shapely.geometry import LineString


ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(ROOT))

import app as web_app  # noqa: E402
from src import exportacion  # noqa: E402
from src.mapas import _filter_background_roads, _road_label_specs, _road_label_style, _subtitle, _subtitle_multitramo, bounds_mapa_principal_multitramo_lonlat  # noqa: E402
from src.tramo import TramoExtraido  # noqa: E402


def tramo(road: str, start: float, end: float, x: float = 0.0) -> TramoExtraido:
    return TramoExtraido(road, "creciente", start, end, start, end, start, end, 1000.0,
                         LineString([(x, 40.0), (x + 0.01, 40.01)]), "EPSG:4326", [], {})


class MultiSegmentContractTests(unittest.TestCase):
    def test_legacy_request_is_valid(self) -> None:
        request = web_app.GenerarRequest(carretera="A-1", pk_inicio=1.0, pk_fin=2.0)
        self.assertIsNone(request.tramos)
        self.assertEqual(request.carretera, "A-1")

    def test_multi_request_is_valid_without_legacy_fields(self) -> None:
        request = web_app.GenerarRequest(tramos=[
            {"carretera": "A-1", "pk_inicio": 1.0, "pk_fin": 2.0},
            {"carretera": "M-11", "pk_inicio": 4.0, "pk_fin": 8.0, "sentido": "decreciente"},
        ], generar_mapa_pendientes=False)
        self.assertEqual(len(request.tramos or []), 2)
        self.assertEqual(request.tramos[1].sentido, "decreciente")

    def test_multi_rejects_slope_map(self) -> None:
        request = web_app.GenerarRequest(tramos=[
            {"carretera": "A-1", "pk_inicio": 1.0, "pk_fin": 2.0},
            {"carretera": "M-11", "pk_inicio": 4.0, "pk_fin": 8.0},
        ])
        with self.assertRaises(web_app.HTTPException) as caught:
            web_app.generar(request)
        self.assertEqual(caught.exception.status_code, 422)

    def test_multi_rejects_generate_all(self) -> None:
        request = web_app.GenerarRequest(tramos=[
            {"carretera": "A-1", "pk_inicio": 1.0, "pk_fin": 2.0},
            {"carretera": "M-11", "pk_inicio": 4.0, "pk_fin": 8.0},
        ], generar_mapa_pendientes=False, generar_todo=True)
        with self.assertRaises(web_app.HTTPException) as caught:
            web_app.generar(request)
        self.assertEqual(caught.exception.status_code, 422)

    def test_single_does_not_enter_multi_dispatcher(self) -> None:
        with patch.object(exportacion, "_generar_outputs_single", return_value={"mode": "single"}) as single, \
             patch.object(exportacion, "_generar_outputs_multitramo") as multi:
            result = exportacion.generar_outputs({"carretera": "A-1", "pk_inicio": 1, "pk_fin": 2})
        self.assertEqual(result["mode"], "single")
        single.assert_called_once()
        multi.assert_not_called()

    def test_one_new_format_segment_uses_single_dispatcher(self) -> None:
        with patch.object(exportacion, "_generar_outputs_single", return_value={"mode": "single"}) as single:
            exportacion.generar_outputs({"tramos": [{"carretera": "A-1", "pk_inicio": 1, "pk_fin": 2, "sentido": "creciente"}]})
        self.assertEqual(single.call_args.args[0]["carretera"], "A-1")


class MultiSegmentMapHelpersTests(unittest.TestCase):
    def test_subtitles_follow_single_and_multi_rules(self) -> None:
        self.assertEqual(_subtitle(tramo("A-1", 150.0, 151.0)), ["A-1 · PK 150+000 a 151+000"])
        self.assertEqual(_subtitle_multitramo([
            {"carretera": "A-1", "pk_inicio": 150.0, "pk_fin": 151.0},
            {"carretera": "M-11", "pk_inicio": 4.5, "pk_fin": 8.2},
        ]), ["A-1 · PK 150+000 a 151+000", "M-11 · PK 4+500 a 8+200"])
        self.assertEqual(_subtitle_multitramo([
            {"carretera": "A-1", "pk_inicio": 1, "pk_fin": 2},
            {"carretera": "M-11", "pk_inicio": 1, "pk_fin": 2},
            {"carretera": "A-1", "pk_inicio": 3, "pk_fin": 4},
            {"carretera": "N-110", "pk_inicio": 1, "pk_fin": 2},
        ]), ["A-1 · M-11 · N-110"])

    def test_background_scope_filter_accepts_all_requested_roads(self) -> None:
        roads = [{"road": "A-1", "type": ""}, {"road": "M-11", "type": ""}, {"road": "N-110", "type": ""}]
        self.assertEqual([item["road"] for item in _filter_background_roads(roads, "ambito", ["A-1", "M-11"])], ["A-1", "M-11"])

    def test_combined_bounds_include_every_geometry(self) -> None:
        bounds = bounds_mapa_principal_multitramo_lonlat([tramo("A-1", 1, 2, -4.0), tramo("M-11", 4, 8, 2.0)])
        self.assertLess(bounds[0], -4.0)
        self.assertGreater(bounds[2], 2.0)

    def test_same_road_scopes_have_distinct_profile_names(self) -> None:
        study = tramo("A-1", 150, 151)
        first = exportacion._scope_slug(study, {"_scope_prefix": "T01"}, profile=True)
        second = exportacion._scope_slug(study, {"_scope_prefix": "T02"}, profile=True)
        self.assertNotEqual(first, second)
        self.assertEqual(first, "T01_A-1_creciente")

    def test_road_labels_are_disabled_for_a_single_distinct_road(self) -> None:
        first, second = tramo("A-1", 1, 2), tramo("A 1", 3, 4, 0.02)
        self.assertEqual(_road_label_specs([first, second], [first.geometry, second.geometry], []), [])

    def test_road_labels_include_each_distinct_study_road_once(self) -> None:
        first, repeated, other = tramo("A-1", 1, 2), tramo("A-1", 3, 4, 0.02), tramo("M-11", 4, 8, 0.04)
        specs = _road_label_specs(
            [first, repeated, other], [first.geometry, repeated.geometry, other.geometry],
            [{"road": "A-1", "type": "Autovía"}, {"road": "M-11", "type": "Convencional"}],
        )
        self.assertEqual([item["carretera"] for item in specs], ["A-1", "M-11"])
        self.assertEqual([item["estilo"]["tipo"] for item in specs], ["autovia", "convencional"])

    def test_road_label_style_distinguishes_autovias(self) -> None:
        self.assertEqual(_road_label_style(True)["texto"], "#ffffff")
        self.assertEqual(_road_label_style(True)["tipo"], "autovia")
        self.assertEqual(_road_label_style(False)["texto"], "#111111")
        self.assertEqual(_road_label_style(False)["tipo"], "convencional")
