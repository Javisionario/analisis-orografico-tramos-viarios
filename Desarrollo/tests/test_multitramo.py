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
from src.mapas import SUBTRAMO_INTERIOR_PALETTE, _filter_background_roads, _road_label_specs, _road_label_style, _subtitle, _subtitle_multitramo, _subtitle_subtramos, bounds_mapa_principal_multitramo_lonlat, subtramo_render_specs  # noqa: E402
from src.subtramos import analizar_subtramos  # noqa: E402
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

    def test_subsegments_accept_same_road_and_direction_and_reject_mixed_semantics(self) -> None:
        valid = web_app.GenerarRequest(tramos=[{"carretera": "A-1", "pk_inicio": 10, "pk_fin": 15}, {"carretera": "A 1", "pk_inicio": 15, "pk_fin": 22}], agrupar_como_subtramos=True, generar_mapa_pendientes=False)
        self.assertTrue(valid.agrupar_como_subtramos)
        for bad in [
            [{"carretera": "A-1", "pk_inicio": 1, "pk_fin": 2}, {"carretera": "M-11", "pk_inicio": 2, "pk_fin": 3}],
            [{"carretera": "A-1", "pk_inicio": 1, "pk_fin": 2, "sentido": "creciente"}, {"carretera": "A-1", "pk_inicio": 2, "pk_fin": 3, "sentido": "decreciente"}],
        ]:
            with self.assertRaises(web_app.HTTPException) as caught:
                web_app.generar(web_app.GenerarRequest(tramos=bad, agrupar_como_subtramos=True, generar_mapa_pendientes=False))
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
    def test_subsegment_global_subtitles_follow_direction(self) -> None:
        entries = [{"carretera": "A-1", "pk_inicio": 10, "pk_fin": 15}, {"carretera": "A-1", "pk_inicio": 15, "pk_fin": 30}]
        self.assertEqual(_subtitle_subtramos(entries, "creciente"), ["A-1 · PK 10+000 a 30+000"])
        self.assertEqual(_subtitle_subtramos(entries, "decreciente"), ["A-1 · PK 30+000 a 10+000"])

    def test_subsegment_gaps_overlaps_and_tolerance_are_reported(self) -> None:
        base = [{"carretera": "A-1", "sentido": "creciente", "pk_inicio": 10, "pk_fin": 15}]
        self.assertTrue(analizar_subtramos(base + [{"carretera": "A-1", "sentido": "creciente", "pk_inicio": 16, "pk_fin": 20}])["huecos"])
        self.assertTrue(analizar_subtramos(base + [{"carretera": "A-1", "sentido": "creciente", "pk_inicio": 14, "pk_fin": 20}])["solapes"])
        self.assertFalse(analizar_subtramos(base + [{"carretera": "A-1", "sentido": "creciente", "pk_inicio": 15.001, "pk_fin": 20}])["huecos"])

    def test_subsegment_topology_is_independent_of_direction_or_endpoint_order(self) -> None:
        for direction, intervals in [
            ("decreciente", [(30, 22), (22, 15), (15, 10)]),
            ("creciente", [(10, 15), (15, 22), (22, 30)]),
            ("creciente", [(15, 10), (20, 15)]),
            ("decreciente", [(22, 30), (15, 22)]),
        ]:
            result = analizar_subtramos([{"carretera": "A-1", "sentido": direction, "pk_inicio": start, "pk_fin": end} for start, end in intervals])
            self.assertFalse(result["huecos"])
            self.assertFalse(result["solapes"])
        self.assertEqual([(item["pk_inicio"], item["pk_fin"]) for item in result["subtramos"]], [(22.0, 30.0), (15.0, 22.0)])
        gap = analizar_subtramos([{"carretera": "A-1", "sentido": "decreciente", "pk_inicio": 30, "pk_fin": 22}, {"carretera": "A-1", "sentido": "decreciente", "pk_inicio": 21, "pk_fin": 15}])
        self.assertEqual(gap["huecos"][0]["entre"], [2, 1])
        overlap = analizar_subtramos([{"carretera": "A-1", "sentido": "decreciente", "pk_inicio": 30, "pk_fin": 20}, {"carretera": "A-1", "sentido": "decreciente", "pk_inicio": 22, "pk_fin": 15}])
        self.assertEqual(overlap["solapes"][0]["entre"], [2, 1])
        tolerant = analizar_subtramos([{"carretera": "A-1", "sentido": "creciente", "pk_inicio": 10, "pk_fin": 15}, {"carretera": "A-1", "sentido": "creciente", "pk_inicio": 15.001, "pk_fin": 20}])
        self.assertFalse(tolerant["huecos"])

    def test_rendered_subsegment_identity_survives_missing_intermediate_scope(self) -> None:
        entries = [
            {"tramo_id": "T01", "original_index": 1, "carretera": "A-1", "pk_inicio": 10, "pk_fin": 15, "sentido": "creciente"},
            {"tramo_id": "T02", "original_index": 2, "carretera": "A-1", "pk_inicio": 15, "pk_fin": 22, "sentido": "creciente"},
            {"tramo_id": "T03", "original_index": 3, "carretera": "A-1", "pk_inicio": 22, "pk_fin": 30, "sentido": "creciente"},
        ]
        specs = subtramo_render_specs(entries, ["T01", "T03"])
        self.assertEqual([(item["tramo_id"], item["original_index"], item["pk_inicio"], item["pk_fin"], item["color"]) for item in specs], [("T01", 1, 10, 15, "#f4a3a8"), ("T03", 3, 22, 30, "#f2b4b8")])

    def test_subsegment_palette_alternates_interiors_and_keeps_common_casing(self) -> None:
        self.assertEqual(SUBTRAMO_INTERIOR_PALETTE[:3], ("#f4a3a8", "#e6858d", "#f2b4b8"))
        self.assertEqual(SUBTRAMO_INTERIOR_PALETTE[1], SUBTRAMO_INTERIOR_PALETTE[3])
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
