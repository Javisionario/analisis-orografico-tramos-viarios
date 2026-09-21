from __future__ import annotations

import sys
import tempfile
import unittest
import json
import subprocess
from zipfile import ZipFile
from pathlib import Path
from unittest.mock import patch

import geopandas as gpd
import pyogrio
from shapely.geometry import LineString, Point

ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(ROOT))

import app as web_app  # noqa: E402
from src.io_datos import detect_columns  # noqa: E402
from src.visor_pks import VALID_INTERVALS, csv_text, export_rows, parse_pk_text, pk_bbox_items, write_gpkg, write_kmz  # noqa: E402


PK_COLS = {"carretera": "MATRICULA", "pk": "VALORKM", "rotacion": "rotacion"}


class ViewerPkTests(unittest.TestCase):
    def test_viewer_height_uses_available_viewport_and_bounds(self) -> None:
        script = (ROOT / "static" / "js" / "road_viewer.js").read_text(encoding="utf-8")
        self.assertIn("MAP_BOTTOM_MARGIN = 20", script)
        self.assertIn("viewerMapHeight(window.innerHeight, rect.top)", script)
        self.assertIn("Math.max(min, Math.min(max", script)
        self.assertIn("resizeViewerMapToViewport", script)
        self.assertIn("MAP_MAX_HEIGHT = 960", script)
        self.assertIn("availableHeight", script)
        self.assertIn("bottomGap", script)
        self.assertNotIn("Acércate para mostrar la red calibrada.", script)

    def test_segment_autocomplete_uses_one_selection_path_and_roles(self) -> None:
        app_script = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        script = (ROOT / "static" / "js" / "segments.js").read_text(encoding="utf-8")
        dynamic_markup = script[script.index("function segmentMarkup"):script.index("function addSegment")]
        self.assertIn("createAnalysisSegments", app_script)
        self.assertEqual(script.count('button.addEventListener("click", () => selectSegmentRoad(segment, item))'), 1)
        self.assertNotIn("setTimeout(() => { segment.querySelector('[data-role=\"suggestions\"]')", script)
        self.assertIn("document.addEventListener(\"pointerdown\"", script)
        self.assertIn("event.target.closest(\".road-field\")", script)
        self.assertIn("!activeRoadField || !segment.contains(activeRoadField)", script)
        self.assertIn("roadField && !roadField.contains(event.relatedTarget)", script)
        self.assertIn("const roadField = event.target.closest(\".road-field\")", script)
        self.assertIn("segment.dataset.suggestionRequest", script)
        self.assertIn("ArrowDown", script)
        self.assertIn("ArrowUp", script)
        self.assertIn("event.key === \"Enter\"", script)
        self.assertIn("event.key === \"Escape\"", script)
        self.assertIn('suggestions.setAttribute("role", "listbox")', script)
        self.assertIn('button.setAttribute("role", "option")', script)
        self.assertIn('data-role="road"', dynamic_markup)
        self.assertIn('aria-expanded="false"', dynamic_markup)
        self.assertNotIn('id="carretera"', dynamic_markup)

    def test_segment_autocomplete_stays_inside_the_scrollable_sidebar(self) -> None:
        styles = (ROOT / "static" / "css" / "styles.css").read_text(encoding="utf-8")
        start = styles.index(".suggestions {")
        block = styles[start:styles.index("}\n", start) + 2]
        self.assertIn("position: relative", block)
        self.assertIn("overflow-y: auto", block)

    def test_viewer_results_navigation_reuses_the_existing_viewer(self) -> None:
        app_script = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        viewer_script = (ROOT / "static" / "js" / "road_viewer.js").read_text(encoding="utf-8")
        self.assertIn('window.showViewerResults = () => showRightPanel("results")', app_script)
        self.assertIn('window.showRoadViewer = () => showRightPanel("viewer")', app_script)
        self.assertIn('show() { requestAnimationFrame(() => requestAnimationFrame(invalidateMapSize)); }', viewer_script)
        self.assertEqual(viewer_script.count("applyNetworkBounds();"), 1)

    def test_generation_error_offers_a_non_destructive_return_to_viewer(self) -> None:
        script = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function setGenerationError(message)", script)
        self.assertIn('button.textContent = "Volver al visor"', script)
        self.assertIn('button.addEventListener("click", () => showRightPanel("viewer"))', script)
        self.assertIn("setGenerationError(String(error.message || error))", script)
        self.assertNotIn("form.reset()", script)

    def test_frontend_escapes_dynamic_status_and_autocomplete_content(self) -> None:
        app_script = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")
        segment_script = (ROOT / "static" / "js" / "segments.js").read_text(encoding="utf-8")
        self.assertIn("function escapeHtml(value)", app_script)
        self.assertIn("heading.textContent = title", app_script)
        self.assertIn("paragraph.textContent = text", app_script)
        self.assertIn("road.textContent = item.carretera", segment_script)
        self.assertIn("if (roadLoading === loading) roadLoading = null", segment_script)
        self.assertIn("safeOutputUrl", app_script)

    def test_export_popover_only_closes_outside_its_wrapper(self) -> None:
        script = (ROOT / "static" / "js" / "road_pk_tools.js").read_text(encoding="utf-8")
        self.assertIn("isOutsideExportClick(wrap, event.target)", script)
        self.assertIn("!wrap.contains(target)", script)
        self.assertNotIn("!wrap.contains(event.target) && !menu?.contains", script)

    def test_network_loading_has_no_transient_visible_status(self) -> None:
        script = (ROOT / "static" / "js" / "road_viewer.js").read_text(encoding="utf-8")
        self.assertNotIn("Cargando red", script)
        self.assertNotIn("Ajustando vista del mapa", script)
        self.assertIn('setNetworkStatus("No se pudo cargar la red calibrada.", true)', script)
        self.assertIn("roadsController?.abort()", script)
        self.assertIn("roadsRequestId", script)

    def test_location_copy_contract_uses_rich_street_view_link_when_available(self) -> None:
        viewer = (ROOT / "static" / "js" / "road_viewer.js").read_text(encoding="utf-8")
        tools = (ROOT / "static" / "js" / "road_pk_tools.js").read_text(encoding="utf-8")
        self.assertIn("Copiar carretera", viewer)
        self.assertIn("Copiar PK", viewer)
        self.assertIn("Copiar coordenadas", viewer)
        self.assertIn("data-copy-coordinates", viewer)
        self.assertIn("function copyCoordinates", viewer)
        self.assertIn("new ClipboardItem", viewer)
        self.assertIn('"text/html"', viewer)
        self.assertIn('`<a href="${escapeHtml(href)}">${escapeHtml(text)}</a>`', viewer)
        self.assertIn('const coordsText = (point) => `${Number(point.lat).toFixed(6)},${Number(point.lon).toFixed(6)}`', viewer)
        self.assertNotIn("Street View:", viewer)
        self.assertIn("locationCopyActions(item)", tools)
        self.assertNotIn("data-pk-copy", tools)
        self.assertNotIn("navigator.clipboard", tools)

    def test_clearing_an_interaction_also_clears_its_result_card(self) -> None:
        viewer = (ROOT / "static" / "js" / "road_viewer.js").read_text(encoding="utf-8")
        self.assertIn('button.addEventListener("click", clearInteractionResult)', viewer)
        self.assertIn("function clearInteractionResult()", viewer)
        clear_block = viewer[viewer.index("function clearInteractionResult()"):viewer.index("function clearInteractionResult()") + 140]
        self.assertIn("clearInteractionGraphics(true)", clear_block)
        self.assertIn('setResult("")', clear_block)

    def test_visible_product_name_uses_the_current_scope(self) -> None:
        product_name = "Orografía y Localización de Tramos Viarios"
        self.assertIn(product_name, (ROOT / "templates" / "index.html").read_text(encoding="utf-8"))
        readme = (ROOT.parent.parent / "README.md").read_text(encoding="utf-8")
        self.assertIn(product_name, readme)
        self.assertNotIn("header_analisis_orografico.webp", readme)
        self.assertIn(product_name, (ROOT.parent.parent / "docs" / "DOCUMENTACION_TECNICA.md").read_text(encoding="utf-8"))
        self.assertIn("Orografia y Localizacion de Tramos Viarios", (ROOT.parent.parent / "iniciar_analisis_orografico_tramos_viarios.bat").read_text(encoding="utf-8"))

    def test_recent_locations_are_mru_bounded_and_separate_from_export_history(self) -> None:
        script = ROOT / "static" / "js" / "road_pk_tools.js"
        check = """
global.window = {};
require(process.argv[1]);
const tools = window.roadPkTools;
let recent = [];
for (let index = 0; index < 13; index += 1) recent = tools.rememberRecent(recent, { carretera: 'A-1', pk: index, punto: { lat: 40, lon: -3 } });
recent = tools.rememberRecent(recent, { carretera: 'A 1', pk: 5, punto: { lat: 40, lon: -3 } });
console.log(JSON.stringify({ max: tools.RECENT_LOCATION_MAX, size: recent.length, first: recent[0], duplicates: recent.filter((item) => tools.recentLocationKey(item) === tools.recentLocationKey({ carretera: 'A-1', pk: 5 })).length }));
"""
        completed = subprocess.run(["node", "-e", check, str(script)], capture_output=True, text=True, check=True)
        result = json.loads(completed.stdout)
        self.assertEqual(result["max"], 12)
        self.assertEqual(result["size"], 12)
        self.assertEqual(result["first"]["pk"], 5)
        self.assertEqual(result["duplicates"], 1)
        text = script.read_text(encoding="utf-8")
        self.assertIn("let recentLocations = []", text)
        self.assertIn("const history = new Map()", text)
        self.assertIn("addHistory(item); addRecentLocation(item)", text)
        self.assertNotIn("addRecentLocation(item);", (ROOT / "static" / "js" / "road_viewer.js").read_text(encoding="utf-8"))

    def test_recent_popover_replays_a_location_and_closes_normally(self) -> None:
        script = (ROOT / "static" / "js" / "road_pk_tools.js").read_text(encoding="utf-8")
        styles = (ROOT / "static" / "css" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("viewerRecentButton", script)
        self.assertIn("viewerRecentMenu", script)
        self.assertIn("function replayRecent", script)
        self.assertIn("locate([{ carretera: item.carretera, pk: item.pk }])", script)
        self.assertIn("closeRecentMenu()", script)
        self.assertIn('document.querySelector("#viewerExportButton")?.setAttribute("aria-expanded", "false")', script)
        self.assertIn(".viewer-recent-wrap", styles)
        self.assertIn(".viewer-recent-menu", styles)

    def test_intervals_match_the_acv_viewer_ladder(self) -> None:
        self.assertEqual(VALID_INTERVALS, {1, 5, 10, 25, 50, 100, 250})
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

    def test_kmz_contains_valid_kml_placemark_and_extended_data(self) -> None:
        rows = export_rows([{"carretera": "A-1", "pk": 31, "longitud": -3.7, "latitud": 40.4}])
        handle = tempfile.NamedTemporaryFile(dir=ROOT, suffix=".kmz", delete=False)
        target = Path(handle.name); handle.close()
        try:
            write_kmz(rows, target)
            with ZipFile(target) as archive:
                self.assertEqual(archive.namelist(), ["doc.kml"])
                kml = archive.read("doc.kml").decode("utf-8")
            self.assertIn("A-1 · PK 31+000", kml)
            self.assertIn("-3.7,40.4,0", kml)
            self.assertIn('Data name="pk_numerico"', kml)
        finally:
            target.unlink(missing_ok=True)

    def test_pk_intervals_filter_twenty_five_and_two_hundred_fifty(self) -> None:
        pks = gpd.GeoDataFrame({"MATRICULA": ["A-1", "A-1", "A-1"], "VALORKM": [25, 50, 250], "rotacion": [0, 0, 0]}, geometry=[Point(0, 0), Point(1000, 0), Point(2000, 0)], crs="EPSG:25830")
        lines = gpd.GeoDataFrame(geometry=[LineString([(0, 0), (2500, 0)])], crs="EPSG:25830")
        self.assertEqual([item["pk"] for item in pk_bbox_items(pks, PK_COLS, lines, ["A-1"], 25)], [25.0, 50.0, 250.0])
        self.assertEqual([item["pk"] for item in pk_bbox_items(pks, PK_COLS, lines, ["A-1"], 250)], [250.0])

    def test_batch_groups_each_resolved_road_once_and_returns_partial_errors(self) -> None:
        payload = web_app.LocalizarPksRequest(puntos=[{"carretera": "A-1", "pk": 1}, {"carretera": "A 1", "pk": 2}, {"carretera": "NO", "pk": 1}])
        with patch.object(web_app, "load_config", return_value={}), patch.object(web_app, "resolve_road_name", side_effect=lambda _c, road: "A-1" if road != "NO" else None), patch.object(web_app, "load_lineas", return_value=(gpd.GeoDataFrame({"ID_ROAD": ["A-1"], "m_from": [0], "m_to": [3000], "Via_sentido": ["A_s_1"]}, geometry=[LineString([(0, 0), (3000, 0)])], crs="EPSG:25830"), {"carretera": "ID_ROAD", "m_inicio": "m_from", "m_fin": "m_to", "sentido": "Via_sentido"}, [])) as load:
            response = web_app.visor_localizar_pks(payload)
        self.assertEqual(load.call_count, 1)
        self.assertEqual([item["indice"] for item in response["resultados"]], [0, 1, 2])
        self.assertIn("error", response["resultados"][2])

    def test_frontend_uses_identified_roads_checkbox_and_popover(self) -> None:
        script = (ROOT / "static" / "js" / "road_pk_tools.js").read_text(encoding="utf-8")
        template = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        styles = (ROOT / "static" / "css" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("VIEWER_PK_MAX_SYMBOLS = 650", script)
        self.assertIn("VIEWER_PK_MAX_LABELS = 90", script)
        self.assertIn("rotation + 90", script)
        self.assertIn("pkDensityForZoom", script)
        self.assertIn("pk-callout", script)
        self.assertIn("selectedRoadsLayer", script)
        self.assertIn('type="checkbox" ${enabled ? "checked" : ""}', script)
        self.assertNotIn("setResult(`<div class=\"viewer-card viewer-export\"", script)
        self.assertIn("Identificar vía", template)
        self.assertIn("viewerExportMenu", template)
        self.assertIn('.viewer-export-menu input[type="checkbox"]', styles)
        self.assertIn(".viewer-export-wrap { position: relative; z-index: 1210", styles)
        self.assertIn(".viewer-export-menu { position: absolute; z-index: 1220; top: calc(100% + 6px); right: 0", styles)
        self.assertIn(".road-viewer-toolbar { position: relative; z-index: 1200", styles)
        self.assertIn(".road-viewer-map .pk-tick", styles)
        self.assertIn(".road-viewer-map .pk-label", styles)
        self.assertIn(".road-viewer-map { position: relative; grid-area: map; height: 500px; min-height: 360px", styles)
        self.assertIn("height: clamp(340px, 52vh, 420px)", styles)
        self.assertIn("background: rgba(255,255,255,.35)", styles)
        self.assertIn('content: "0"', styles)
        self.assertIn("center bottom 7px / 1px 2px no-repeat", styles)
        viewer_script = (ROOT / "static" / "js" / "road_viewer.js").read_text(encoding="utf-8")
        self.assertIn('L.control.scale({ position: "bottomleft", metric: true, imperial: false, maxWidth: 180 })', viewer_script)
        self.assertNotIn("mapElement.appendChild(exportMenu)", viewer_script)

    def test_frontend_density_keeps_non_divisible_labels_and_hard_limits(self) -> None:
        script = ROOT / "static" / "js" / "road_pk_tools.js"
        check = """
global.window = {};
require(process.argv[1]);
const tools = window.roadPkTools;
const sparse = [
  { carretera: 'A-1', pk: 10, lon: 0, lat: 0 },
  { carretera: 'A-1', pk: 25, lon: 1, lat: 1 },
  { carretera: 'A-1', pk: 100, lon: 2, lat: 2 },
  { carretera: 'A-1', pk: 250, lon: 3, lat: 3 },
];
const dense = Array.from({ length: 1000 }, (_, index) => ({ carretera: 'A-1', pk: 0, lon: index / 10000, lat: index / 10000 }));
const z10 = tools.overlaySelection(sparse, 10);
const z5 = tools.overlaySelection(sparse, 5);
const capped = tools.overlaySelection(dense, 15);
console.log(JSON.stringify({
  z10Source: tools.sourceIntervalForZoom(10),
  z10Labels: z10.labelItems.map((item) => item.pk),
  z5Source: tools.sourceIntervalForZoom(5),
  z5Labels: z5.labelItems.map((item) => item.pk),
  symbols: capped.symbolItems.length,
  labels: capped.labelItems.length,
  labelsDrawn: z10.labelItems.every((label) => z10.symbolItems.some((symbol) => symbol.pk === label.pk && symbol.lon === label.lon && symbol.lat === label.lat)) && z5.labelItems.every((label) => z5.symbolItems.some((symbol) => symbol.pk === label.pk && symbol.lon === label.lon && symbol.lat === label.lat)),
}));
"""
        completed = subprocess.run(["node", "-e", check, str(script)], capture_output=True, text=True, check=True)
        result = json.loads(completed.stdout)
        self.assertEqual(result["z10Source"], 5)
        self.assertIn(25, result["z10Labels"])
        self.assertEqual(result["z5Source"], 50)
        self.assertEqual(result["z5Labels"], [250])
        self.assertTrue(result["labelsDrawn"])
        self.assertEqual(result["symbols"], 650)
        self.assertEqual(result["labels"], 90)


if __name__ == "__main__":
    unittest.main()
