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
from src.mapas import DIVISION_INTERIOR_PALETTE, _filter_background_roads, _road_label_specs, _road_label_style, _subtitle, _subtitle_multitramo, bounds_mapa_principal_multitramo_lonlat  # noqa: E402
from src.subtramos import DivisionError, derivar_subtramos, normalizar_divisiones  # noqa: E402
from src.tramo import TramoExtraido  # noqa: E402


def tramo(road: str, start: float, end: float, x: float = 0.0) -> TramoExtraido:
    return TramoExtraido(road, "creciente", start, end, start, end, start, end, 1000.0,
                         LineString([(x, 40.0), (x + 0.01, 40.01)]), "EPSG:4326", [], {})


class DivisionContractTests(unittest.TestCase):
    def test_legacy_single_request_is_valid(self) -> None:
        request = web_app.GenerarRequest(carretera="A-1", pk_inicio=1.0, pk_fin=2.0)
        self.assertIsNone(request.tramos)

    def test_divisions_belong_to_each_real_segment(self) -> None:
        request = web_app.GenerarRequest(tramos=[{"carretera": "A-1", "pk_inicio": 10, "pk_fin": 50, "divisiones_pk": [30, 15]}])
        self.assertEqual(request.tramos[0].divisiones_pk, [30.0, 15.0])

    def test_legacy_grouping_is_rejected_explicitly(self) -> None:
        request = web_app.GenerarRequest(carretera="A-1", pk_inicio=1, pk_fin=2, agrupar_como_subtramos=True)
        with self.assertRaises(web_app.HTTPException) as caught:
            web_app.generar(request)
        self.assertEqual(caught.exception.status_code, 422)

    def test_invalid_division_is_rejected(self) -> None:
        request = web_app.GenerarRequest(tramos=[{"carretera": "A-1", "pk_inicio": 10, "pk_fin": 20, "divisiones_pk": [10]}])
        with self.assertRaises(web_app.HTTPException) as caught:
            web_app.generar(request)
        self.assertEqual(caught.exception.status_code, 422)

    def test_one_real_segment_keeps_single_dispatcher(self) -> None:
        params = {"tramos": [{"carretera": "A-1", "pk_inicio": 1, "pk_fin": 2, "sentido": "creciente", "divisiones_pk": [1.5]}]}
        with patch.object(exportacion, "_generar_outputs_single", return_value={"mode": "single"}) as single:
            exportacion.generar_outputs(params)
        self.assertEqual(single.call_args.args[0]["divisiones_pk"], [1.5])

    def test_multi_rejects_slope_map(self) -> None:
        request = web_app.GenerarRequest(tramos=[{"carretera": "A-1", "pk_inicio": 1, "pk_fin": 2}, {"carretera": "M-11", "pk_inicio": 4, "pk_fin": 8}])
        with self.assertRaises(web_app.HTTPException):
            web_app.generar(request)


class DivisionHelperTests(unittest.TestCase):
    def test_increasing_unsorted_divisions_cover_the_route(self) -> None:
        self.assertEqual([(x["pk_inicio"], x["pk_fin"]) for x in derivar_subtramos(10, 50, [30, 15])], [(10, 15), (15, 30), (30, 50)])

    def test_decreasing_unsorted_divisions_follow_route(self) -> None:
        self.assertEqual([(x["pk_inicio"], x["pk_fin"]) for x in derivar_subtramos(50, 10, [15, 30], "decreciente")], [(50, 30), (30, 15), (15, 10)])

    def test_normalized_values_exclude_endpoints_in_both_directions(self) -> None:
        self.assertEqual(normalizar_divisiones(10, 50, [30, 15], "creciente"), [15, 30])
        self.assertEqual(normalizar_divisiones(50, 10, [15, 30], "decreciente"), [30, 15])

    def test_ambos_has_a_derivation_for_each_real_direction(self) -> None:
        self.assertEqual(derivar_subtramos(10, 50, [15, 30], "creciente")[0]["pk_inicio"], 10)
        self.assertEqual(derivar_subtramos(10, 50, [15, 30], "decreciente")[0]["pk_inicio"], 50)

    def test_invalid_endpoints_duplicates_and_outside_are_rejected(self) -> None:
        for values in ([10], [20], [15, 15], [9]):
            with self.assertRaises(DivisionError):
                normalizar_divisiones(10, 20, values)

    def test_tolerance_rejects_near_duplicates(self) -> None:
        with self.assertRaises(DivisionError):
            normalizar_divisiones(10, 20, [15, 15.001])

    def test_division_palette_alternates(self) -> None:
        self.assertEqual(DIVISION_INTERIOR_PALETTE, ("#f4a3a8", "#df7f87"))


class MultiSegmentMapHelpersTests(unittest.TestCase):
    def test_subtitles_remain_real_segment_subtitles(self) -> None:
        self.assertEqual(_subtitle(tramo("A-1", 150, 151)), ["A-1 · PK 150+000 a 151+000"])
        self.assertEqual(_subtitle_multitramo([{"carretera": "A-1", "pk_inicio": 1, "pk_fin": 2}, {"carretera": "M-11", "pk_inicio": 4, "pk_fin": 8}]), ["A-1 · PK 1+000 a 2+000", "M-11 · PK 4+000 a 8+000"])

    def test_background_scope_filter_accepts_all_requested_roads(self) -> None:
        roads = [{"road": "A-1", "type": ""}, {"road": "M-11", "type": ""}, {"road": "N-110", "type": ""}]
        self.assertEqual([item["road"] for item in _filter_background_roads(roads, "ambito", ["A-1", "M-11"])], ["A-1", "M-11"])

    def test_combined_bounds_include_every_geometry(self) -> None:
        bounds = bounds_mapa_principal_multitramo_lonlat([tramo("A-1", 1, 2, -4), tramo("M-11", 4, 8, 2)])
        self.assertLess(bounds[0], -4)
        self.assertGreater(bounds[2], 2)

    def test_road_labels_include_each_distinct_study_road_once(self) -> None:
        first, repeated, other = tramo("A-1", 1, 2), tramo("A-1", 3, 4, .02), tramo("M-11", 4, 8, .04)
        specs = _road_label_specs([first, repeated, other], [first.geometry, repeated.geometry, other.geometry], [{"road": "A-1", "type": "Autovía"}, {"road": "M-11", "type": "Convencional"}])
        self.assertEqual([item["carretera"] for item in specs], ["A-1", "M-11"])
        self.assertEqual(_road_label_style(True)["tipo"], "autovia")
