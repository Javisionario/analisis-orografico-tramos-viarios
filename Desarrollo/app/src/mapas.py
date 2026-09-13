from __future__ import annotations

import math
from pathlib import Path
from time import perf_counter
from typing import Any

import geopandas as gpd
import numpy as np
import rasterio
from PIL import Image, ImageColor, ImageDraw
from rasterio.enums import Resampling
from rasterio.transform import from_bounds as transform_from_bounds
from rasterio.warp import reproject, transform_bounds
from shapely.geometry import box

from .compositor_cartografico_pil import (
    MAP_DPI,
    MAP_HEIGHT,
    MAP_INSET,
    MAP_LEGEND_HEADING_STEP_PX,
    MAP_LEGEND_Y_OFFSET_CM,
    MAP_MAIN,
    MAP_WIDTH,
    PK_ALLOWED_INTERVALS,
    PK_CALLOUT_WIDTH,
    PK_LABEL_FONT_SIZE,
    PK_LABEL_OFFSET_SCALE,
    PK_TICK_HALF_LENGTH,
    PK_TICK_WIDTH,
    TILE_ERROR_SAMPLES,
    TILE_ERRORS,
    clip_overlay,
    draw_admin_boundaries,
    draw_inset_frame,
    draw_inset_outline,
    draw_left_title,
    draw_legend_rows,
    draw_main_frame,
    draw_main_outline,
    draw_north_arrow,
    draw_output_border,
    draw_polyline,
    draw_scale_bar,
    draw_text_halo,
    fit_bounds_to_clip,
    line_coordinate_sequences,
    make_projector,
    map_metadata,
    new_canvas,
    overview_bounds_from_main,
    pil_font,
    pk_tick_angle,
    point_segment_distance,
    render_report_basemap,
    save_pdf_rgb,
    save_png_rgb,
    text_size,
)
from .estilos import elevation_colors, nice_elevation_classes_with_metadata, slope_classes
from .io_datos import normalize_road_name
from .tramo import TramoExtraido
from .utils import as_float, format_pk


STUDY_LINE_WIDTHS_OLD = {"borde": 22, "centro": 13}
STUDY_LINE_WIDTHS_NEW = {"borde": 44, "centro": 26}
SLOPE_LINE_WIDTHS_OLD = {"borde": 22, "centro": 13}
SLOPE_LINE_WIDTHS_NEW = {"borde": 44, "centro": 26}


def _to_4326_gdf(gdf: gpd.GeoDataFrame | None, fallback_crs: Any = None) -> gpd.GeoDataFrame:
    if gdf is None or gdf.empty:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    result = gdf.copy()
    if result.crs is None and fallback_crs is not None:
        result = result.set_crs(fallback_crs, allow_override=True)
    if result.crs is not None:
        try:
            if result.crs.to_epsg() != 4326:
                result = result.to_crs(epsg=4326)
        except Exception:
            result = result.to_crs(epsg=4326)
    return result


def _to_4326_geom(geometry: Any, crs: Any) -> Any:
    if geometry is None:
        return None
    if crs is None:
        return geometry
    return gpd.GeoSeries([geometry], crs=crs).to_crs(epsg=4326).iloc[0]


def _expanded_lonlat_bounds(geometry: Any) -> tuple[float, float, float, float]:
    lon_min, lat_min, lon_max, lat_max = geometry.bounds
    width = max(lon_max - lon_min, 1e-6)
    height = max(lat_max - lat_min, 1e-6)
    lon_pad = max(width * 0.16, 0.006)
    lat_pad = max(height * 0.16, 0.006)
    return lon_min - lon_pad, lat_min - lat_pad, lon_max + lon_pad, lat_max + lat_pad


def _bbox_filter(gdf: gpd.GeoDataFrame, bounds: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    if gdf is None or gdf.empty:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    try:
        return gdf[gdf.geometry.intersects(box(*bounds))].copy()
    except Exception:
        return gdf.copy()


def _is_autovia(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return any(token in text for token in ("autov", "autop", "motorway", "dual"))


def _road_records(lineas: gpd.GeoDataFrame, cols: dict[str, str | None], bounds: tuple[float, float, float, float]) -> list[dict[str, Any]]:
    if lineas is None or lineas.empty:
        return []
    subset = _bbox_filter(lineas, bounds)
    road_col = cols.get("carretera")
    type_col = cols.get("tipo_via")
    records: list[dict[str, Any]] = []
    for _, row in subset.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        records.append(
            {
                "geometry": geom,
                "road": str(row.get(road_col, "")) if road_col else "",
                "type": str(row.get(type_col, "")) if type_col else "",
            }
        )
    return records


def _same_road(left: str, right: str) -> bool:
    normalize = lambda value: "".join(ch for ch in str(value or "").upper() if ch.isalnum())
    return normalize(left) == normalize(right)


def _filter_background_roads(roads: list[dict[str, Any]], mode: str, road_name: str) -> list[dict[str, Any]]:
    mode_norm = str(mode or "todas").strip().lower()
    if mode_norm in {"ninguna", "none", "no"}:
        return []
    if mode_norm in {"ambito", "via_ambito", "solo_ambito", "solo_via"}:
        return [road for road in roads if _same_road(road.get("road", ""), road_name)]
    if mode_norm in {"autovias", "solo_autovias", "autovia"}:
        return [road for road in roads if _is_autovia(road.get("type")) or _same_road(road.get("road", ""), road_name)]
    return roads


def _draw_background_roads(canvas: Image.Image, roads: list[dict[str, Any]], project: Any, clip: tuple[int, int, int, int]) -> list[tuple[float, float, float, float]]:
    overlay = Image.new("RGBA", (MAP_WIDTH, MAP_HEIGHT), (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    segments: list[tuple[float, float, float, float]] = []
    for road in roads:
        autovia = _is_autovia(road.get("type"))
        for coords in line_coordinate_sequences(road.get("geometry")):
            projected = [project(lon, lat) for lon, lat, *_ in coords]
            for (ax, ay), (bx, by) in zip(projected, projected[1:]):
                segments.append((ax, ay, bx, by))
            if autovia:
                draw_polyline(draw, projected, "#2d539e", 13)
                draw_polyline(draw, projected, "#ffffff", 5)
            else:
                draw_polyline(draw, projected, "#4a4a4a", 9)
                draw_polyline(draw, projected, "#ffffff", 4)
    clip_overlay(canvas, overlay, clip)
    return segments


def _draw_round_polyline(draw: ImageDraw.ImageDraw, coords: list[tuple[float, float]], fill: str, width: int) -> None:
    if len(coords) < 2:
        return
    draw_polyline(draw, coords, fill, width)
    radius = max(1.0, float(width) / 2.0)
    for x, y in (coords[0], coords[-1]):
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)


def _draw_study_line(canvas: Image.Image, geometry: Any, project: Any, clip: tuple[int, int, int, int]) -> None:
    overlay = Image.new("RGBA", (MAP_WIDTH, MAP_HEIGHT), (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    for coords in line_coordinate_sequences(geometry):
        projected = [project(lon, lat) for lon, lat, *_ in coords]
        _draw_round_polyline(draw, projected, "#7f1d1d", STUDY_LINE_WIDTHS_NEW["borde"])
        _draw_round_polyline(draw, projected, "#f4a3a8", STUDY_LINE_WIDTHS_NEW["centro"])
    clip_overlay(canvas, overlay, clip)


def _draw_slope_segments(canvas: Image.Image, tramo_geom: Any, segmentos: gpd.GeoDataFrame, project: Any, clip: tuple[int, int, int, int]) -> None:
    overlay = Image.new("RGBA", (MAP_WIDTH, MAP_HEIGHT), (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    for coords in line_coordinate_sequences(tramo_geom):
        _draw_round_polyline(draw, [project(lon, lat) for lon, lat, *_ in coords], "#111111", SLOPE_LINE_WIDTHS_NEW["borde"])
    if segmentos is not None and not segmentos.empty:
        for _, row in segmentos.iterrows():
            color = str(row.get("color", "#f1f1f1"))
            for coords in line_coordinate_sequences(row.geometry):
                _draw_round_polyline(draw, [project(lon, lat) for lon, lat, *_ in coords], color, SLOPE_LINE_WIDTHS_NEW["centro"])
    clip_overlay(canvas, overlay, clip)


def _pk_matches_interval(pk: float, interval: int | None) -> bool:
    if interval is None:
        return False
    if interval not in PK_ALLOWED_INTERVALS:
        return False
    return int(round(float(pk))) % interval == 0


def _automatic_pk_intervals(length_km: float) -> tuple[int, int]:
    if length_km <= 10:
        return 1, 1
    if length_km <= 30:
        return 1, 5
    if length_km <= 80:
        return 5, 10
    if length_km <= 150:
        return 10, 25
    if length_km <= 300:
        return 25, 50
    return 50, 100


def _resolve_pk_map_config(tramo: TramoExtraido, pintar: bool, pk_options: dict[str, Any] | None = None) -> dict[str, Any]:
    pk_options = pk_options or {}
    length_km = abs(float(tramo.pk_fin_recorrido) - float(tramo.pk_inicio_recorrido))
    mode = str(pk_options.get("modo") or pk_options.get("pk_modo") or "automatico").strip().lower()
    if not pintar or mode in {"no_mostrar", "no", "none", "ocultar"}:
        return {
            "modo": "no_mostrar",
            "simbolo_cada_pk": None,
            "etiqueta_cada_pk": None,
            "mostrar_simbolos": False,
            "mostrar_etiquetas": False,
            "longitud_ambito_km": round(length_km, 3),
            "origen_configuracion": "no_mostrar",
        }
    if mode == "manual":
        symbol = int(pk_options.get("simbolo_cada_pk") or 1)
        label = int(pk_options.get("etiqueta_cada_pk") or symbol)
        if symbol not in PK_ALLOWED_INTERVALS:
            symbol = 1
        if label not in PK_ALLOWED_INTERVALS:
            label = symbol
        if label < symbol:
            label = symbol
        origin = "manual"
    else:
        symbol, label = _automatic_pk_intervals(length_km)
        origin = "automatico"
    return {
        "modo": mode if mode == "manual" else "automatico",
        "simbolo_cada_pk": symbol,
        "etiqueta_cada_pk": label,
        "mostrar_simbolos": True,
        "mostrar_etiquetas": True,
        "longitud_ambito_km": round(length_km, 3),
        "origen_configuracion": origin,
    }


def _pk_items(
    pks: gpd.GeoDataFrame,
    pk_cols: dict[str, str | None],
    tramo: TramoExtraido,
    bounds: tuple[float, float, float, float],
    pk_config: dict[str, Any],
) -> list[dict[str, Any]]:
    if not pk_config.get("mostrar_simbolos") or pks is None or pks.empty:
        return []
    pk_col = pk_cols.get("pk")
    label_col = pk_cols.get("label")
    road_col = pk_cols.get("carretera")
    if not pk_col or pk_col not in pks.columns:
        return []
    symbol_interval = pk_config.get("simbolo_cada_pk")
    label_interval = pk_config.get("etiqueta_cada_pk")
    lon_min, lat_min, lon_max, lat_max = bounds
    items: list[dict[str, Any]] = []
    for _, row in pks.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        if road_col and road_col in pks.columns and normalize_road_name(row.get(road_col)) != normalize_road_name(tramo.carretera):
            continue
        pk = as_float(row.get(pk_col))
        if pk is None:
            continue
        if pk > 1000:
            pk = pk / 1000.0
        if not _pk_matches_interval(pk, symbol_interval):
            continue
        # Los PKs se representan por encuadre cartografico, no solo por el
        # rango exacto del tramo. Si la capa aporta carretera, se comprueba
        # tambien aqui para no dibujar PKs de otras vias.
        if not (lon_min <= geom.x <= lon_max and lat_min <= geom.y <= lat_max):
            continue
        label = str(row.get(label_col)) if label_col and row.get(label_col) not in (None, "") else format_pk(pk)
        items.append({"lon": geom.x, "lat": geom.y, "label": label, "km": pk, "mostrar_etiqueta": _pk_matches_interval(pk, label_interval)})
    return items


def _draw_pks(
    canvas: Image.Image,
    items: list[dict[str, Any]],
    roads: list[dict[str, Any]],
    project: Any,
    road_segments: list[tuple[float, float, float, float]],
    clip: tuple[int, int, int, int],
) -> None:
    if not items:
        return
    map_x, map_y, map_w, map_h = clip
    overlay = Image.new("RGBA", (MAP_WIDTH, MAP_HEIGHT), (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    label_font = pil_font(PK_LABEL_FONT_SIZE, bold=False)
    used_boxes: list[tuple[float, float, float, float]] = []
    base_offsets = [(190, -92), (-190, -92), (190, 100), (-190, 100), (235, -28), (-235, -28), (88, -158), (-88, -158), (88, 164), (-88, 164)]
    label_offsets = [(int(round(dx * PK_LABEL_OFFSET_SCALE)), int(round(dy * PK_LABEL_OFFSET_SCALE))) for dx, dy in base_offsets]
    map_mid_x = map_x + map_w / 2
    for item in items:
        x, y = project(item["lon"], item["lat"])
        rotation = pk_tick_angle(item, roads, project)
        angle = math.radians(rotation)
        tick_dx = math.cos(angle) * PK_TICK_HALF_LENGTH
        tick_dy = math.sin(angle) * PK_TICK_HALF_LENGTH
        draw.line((x - tick_dx, y - tick_dy, x + tick_dx, y + tick_dy), fill="#111111", width=PK_TICK_WIDTH)
        if not item.get("mostrar_etiqueta", True):
            continue
        text = str(item["label"])
        text_w, text_h = text_size(draw, text, label_font)
        preferred = 1 if x < map_mid_x else -1
        candidates = label_offsets if preferred > 0 else [(-dx, dy) for dx, dy in label_offsets]
        best: tuple[float, float, float, float, str, tuple[float, float, float, float]] | None = None
        best_score = float("inf")
        for dx, dy in candidates:
            label_x, label_y = x + dx, y + dy
            if dx >= 0:
                box_item = (label_x, label_y - text_h / 2 - 8, label_x + text_w, label_y + text_h / 2 + 8)
                anchor = "lm"
                line_end_x = label_x - 18
            else:
                box_item = (label_x - text_w, label_y - text_h / 2 - 8, label_x, label_y + text_h / 2 + 8)
                anchor = "rm"
                line_end_x = label_x + 18
            score = abs(dy) * 0.25 + abs(dx) * 0.05
            if box_item[0] < map_x + 8 or box_item[2] > map_x + map_w - 8 or box_item[1] < map_y + 8 or box_item[3] > map_y + map_h - 8:
                score += 2000
            if any(not (box_item[2] < other[0] or other[2] < box_item[0] or box_item[3] < other[1] or other[3] < box_item[1]) for other in used_boxes):
                score += 900
            centre_x = (box_item[0] + box_item[2]) / 2
            centre_y = (box_item[1] + box_item[3]) / 2
            road_distance = min([point_segment_distance(centre_x, centre_y, *segment) for segment in road_segments] + [999])
            if road_distance < 54:
                score += (54 - road_distance) * 18
            if score < best_score:
                best_score = score
                best = (label_x, label_y, line_end_x, label_y, anchor, box_item)
        if best:
            label_x, label_y, line_end_x, line_end_y, anchor, label_box = best
            draw.line((x, y, line_end_x, line_end_y), fill="#4f5963", width=PK_CALLOUT_WIDTH)
            draw_text_halo(draw, (label_x, label_y), text, label_font, "#303030", anchor=anchor, stroke_width=5)
            used_boxes.append(label_box)
    clip_overlay(canvas, overlay, clip)


def _rgba(hex_color: str, alpha: float) -> tuple[int, int, int, int]:
    r, g, b = ImageColor.getrgb(hex_color)
    return r, g, b, max(0, min(255, int(round(float(alpha) * 255))))


def _draw_two_column_slope_legend(
    draw: ImageDraw.ImageDraw,
    start_y: int,
    elevation_rows: list[tuple[str, str, str]],
    slope_rows: list[tuple[str, str, str]],
) -> dict[str, Any]:
    left_x = MAP_INSET[0] + 6
    total_width = MAP_INSET[2] - 12
    gap = 10
    col_w = int((total_width - gap) / 2)
    font = pil_font(58, bold=False)
    heading_font = pil_font(65, bold=True)
    row_step = 100
    heading_gap = 150
    swatch_w = 62
    swatch_h = 38

    def draw_column(x: int, y: int, title: str, rows: list[tuple[str, str, str]]) -> int:
        draw.text((x, y), title, font=heading_font, fill="#111111", anchor="la")
        cursor = y + heading_gap
        for label, color, _style in rows:
            symbol_center_y = cursor
            symbol_top = symbol_center_y - swatch_h / 2
            symbol_bottom = symbol_center_y + swatch_h / 2
            draw.rectangle((x, symbol_top, x + swatch_w, symbol_bottom), fill=color, outline="#9da5a8", width=2)
            text = str(label)
            if len(text) > 24:
                text = text[:23] + "."
            draw.text((x + swatch_w + 16, symbol_center_y), text, font=font, fill="#151515", anchor="lm")
            cursor += row_step
        return cursor

    elev_end = draw_column(left_x, start_y, "Elevaciones", elevation_rows)
    slope_end = draw_column(left_x + col_w + gap, start_y, "Pendientes", slope_rows)
    return {
        "leyenda_pendientes_columnas": 2,
        "leyenda_pendientes_font_size": 58,
        "leyenda_pendientes_heading_font_size": 68,
        "leyenda_pendientes_columna_gap_px": gap,
        "legend_two_col_heading_gap_px": heading_gap,
        "legend_two_col_row_step_px": row_step,
        "legend_two_col_swatch_w_px": swatch_w,
        "legend_two_col_swatch_h_px": swatch_h,
        "legend_alignment_method": "symbol_and_text_centered",
        "leyenda_pendientes_start_px": [int(left_x), int(start_y)],
        "leyenda_pendientes_columna_ancho_px": col_w,
        "leyenda_pendientes_end_y_px": int(max(elev_end, slope_end)),
    }


def _read_raster_for_bounds(
    raster_path: Path | None,
    bounds_lonlat: tuple[float, float, float, float],
    clip: tuple[int, int, int, int],
) -> tuple[np.ndarray | None, dict[str, Any], list[str]]:
    warnings: list[str] = []
    if not raster_path or not Path(raster_path).exists():
        return None, {
            "mdt_path": str(raster_path) if raster_path else None,
            "mdt_exists": False,
            "elevaciones_motivo_no_renderizado": "No hay MDT disponible para pintar elevaciones/curvas en mapa.",
        }, ["No hay MDT disponible para pintar elevaciones/curvas en mapa."]
    try:
        with rasterio.open(raster_path) as src:
            base_meta = {
                "mdt_path": str(raster_path),
                "mdt_exists": True,
                "mdt_crs": str(src.crs) if src.crs else None,
                "mdt_bounds": tuple(float(v) for v in src.bounds),
                "mdt_width": int(src.width),
                "mdt_height": int(src.height),
                "mdt_nodata": src.nodata,
                "mdt_resolution": tuple(float(v) for v in src.res),
            }
            if src.crs is None:
                base_meta["elevaciones_motivo_no_renderizado"] = "El MDT no tiene CRS; no se puede reproyectar al mapa."
                return None, base_meta, ["El MDT no tiene CRS; no se puede reproyectar al mapa."]
            src_bounds = transform_bounds("EPSG:4326", src.crs, *bounds_lonlat, densify_pts=21)
            raster_bounds = tuple(float(v) for v in src.bounds)
            if src_bounds[2] <= raster_bounds[0] or src_bounds[0] >= raster_bounds[2] or src_bounds[3] <= raster_bounds[1] or src_bounds[1] >= raster_bounds[3]:
                base_meta["elevaciones_motivo_no_renderizado"] = "El MDT no intersecta el encuadre del mapa."
                return None, base_meta, ["El MDT no intersecta el encuadre del mapa."]
            target_bounds_3857 = transform_bounds("EPSG:4326", "EPSG:3857", *bounds_lonlat, densify_pts=21)
            target_w = int(clip[2])
            target_h = int(clip[3])
            dst_transform = transform_from_bounds(*target_bounds_3857, target_w, target_h)
            arr = np.full((target_h, target_w), np.nan, dtype=np.float32)
            reproject(
                source=rasterio.band(src, 1),
                destination=arr,
                src_transform=src.transform,
                src_crs=src.crs,
                src_nodata=src.nodata,
                dst_transform=dst_transform,
                dst_crs="EPSG:3857",
                dst_nodata=np.nan,
                resampling=Resampling.bilinear,
            )
            nodata = src.nodata
            if nodata is not None:
                arr[np.isclose(arr, float(nodata))] = np.nan
            finite = arr[np.isfinite(arr)]
            meta = {
                **base_meta,
                "mdt_min": float(np.nanmin(finite)) if len(finite) else None,
                "mdt_max": float(np.nanmax(finite)) if len(finite) else None,
                "raster_overlay_shape": [int(target_h), int(target_w)],
                "elevaciones_reproyectadas": True,
                "elevaciones_crs_origen": str(src.crs),
                "elevaciones_crs_destino": "EPSG:3857",
                "elevaciones_target_bounds_3857": [float(v) for v in target_bounds_3857],
                "elevaciones_target_width": int(target_w),
                "elevaciones_target_height": int(target_h),
                "elevaciones_transform_destino": tuple(float(v) for v in dst_transform),
                "elevaciones_resampling": "bilinear",
                "elevaciones_alineacion": "reproject_to_webmercator_map_main",
            }
            return arr, meta, warnings
    except Exception as exc:
        return None, {
            "mdt_path": str(raster_path) if raster_path else None,
            "mdt_exists": bool(raster_path and Path(raster_path).exists()),
            "elevaciones_motivo_no_renderizado": f"No se pudo leer MDT para mapa: {exc}",
        }, [f"No se pudo leer MDT para mapa: {exc}"]


def _prepared_raster_for_map(
    raster_path: Path | None,
    bounds_lonlat: tuple[float, float, float, float],
    clip: tuple[int, int, int, int],
    cache: dict[tuple[Any, ...], tuple[np.ndarray | None, dict[str, Any], list[str]]] | None = None,
) -> tuple[np.ndarray | None, dict[str, Any], list[str]]:
    """Reutiliza el MDT ya reproyectado cuando dos mapas comparten encuadre."""
    key = (
        str(Path(raster_path).resolve()) if raster_path else None,
        tuple(round(float(value), 9) for value in bounds_lonlat),
        tuple(int(value) for value in clip),
    )
    if cache is not None and key in cache:
        return cache[key]
    result = _read_raster_for_bounds(raster_path, bounds_lonlat, clip)
    if cache is not None:
        cache[key] = result
    return result


def _render_elevation_overlay(
    canvas: Image.Image,
    raster_data: np.ndarray | None,
    bounds_lonlat: tuple[float, float, float, float],
    clip: tuple[int, int, int, int],
    alpha: float,
    config: dict[str, Any],
) -> dict[str, Any]:
    if raster_data is None or not np.any(np.isfinite(raster_data)):
        return {
            "elevaciones_intento_renderizado": True,
            "elevaciones_renderizadas": False,
            "elevaciones_motivo_no_renderizado": "Raster inexistente, fuera de ambito o sin valores finitos.",
            "elevaciones_clases": [],
            "elevaciones_alpha": float(alpha),
            "orden_composicion": "Positron -> elevaciones -> curvas -> vias -> tramo/pendientes -> PKs -> marcos/leyenda",
        }
    finite = raster_data[np.isfinite(raster_data)]
    classes, class_meta = nice_elevation_classes_with_metadata(finite, max_classes=6)
    if not classes:
        return {
            "elevaciones_intento_renderizado": True,
            "elevaciones_renderizadas": False,
            "elevaciones_motivo_no_renderizado": "No se pudieron generar clases de elevacion.",
            "elevaciones_clases": [],
            **class_meta,
            "elevaciones_alpha": float(alpha),
            "orden_composicion": "Positron -> elevaciones -> curvas -> vias -> tramo/pendientes -> PKs -> marcos/leyenda",
        }
    colors = elevation_colors(config)
    rgba = np.zeros((raster_data.shape[0], raster_data.shape[1], 4), dtype=np.uint8)
    for idx, klass in enumerate(classes):
        color = _rgba(colors[min(idx, len(colors) - 1)], alpha)
        low = float(klass["min"])
        high = float(klass["max"])
        if idx == len(classes) - 1:
            mask = np.isfinite(raster_data) & (raster_data >= low) & (raster_data <= high)
        else:
            mask = np.isfinite(raster_data) & (raster_data >= low) & (raster_data < high)
        rgba[mask] = color
        klass["color"] = colors[min(idx, len(colors) - 1)]
    image = Image.fromarray(rgba, mode="RGBA")
    canvas.alpha_composite(image, (clip[0], clip[1]))
    return {
        "elevaciones_renderizadas": True,
        "elevaciones_intento_renderizado": True,
        "elevaciones_clases": classes,
        **class_meta,
        "elevaciones_alpha": float(alpha),
        "elevaciones_motivo_no_renderizado": None,
        "elevaciones_bounds_lonlat": bounds_lonlat,
        "elevaciones_target_width": int(clip[2]),
        "elevaciones_target_height": int(clip[3]),
        "elevaciones_alineacion": "reproject_to_webmercator_map_main",
        "orden_composicion": "Positron -> elevaciones -> curvas -> vias -> tramo/pendientes -> PKs -> marcos/leyenda",
    }


def _contour_levels(classes: list[dict[str, Any]]) -> tuple[list[float], list[float], float | None, float | None]:
    if len(classes) < 1:
        return [], [], None, None
    edges = [float(item["min"]) for item in classes] + [float(classes[-1]["max"])]
    edges = sorted(set(edges))
    if len(edges) < 2:
        return [], [], None, None
    main_step = edges[1] - edges[0]
    if main_step <= 0:
        return [], [], None, None
    intermediate_step = main_step / 2.0
    zmin, zmax = edges[0], edges[-1]
    intermediate = []
    value = zmin + intermediate_step
    while value < zmax - 1e-9:
        if all(abs(value - edge) > 1e-6 for edge in edges):
            intermediate.append(float(value))
        value += intermediate_step
    return intermediate, edges, intermediate_step, main_step


def _polyline_lengths(points: list[tuple[float, float]]) -> tuple[list[float], float]:
    cumulative = [0.0]
    total = 0.0
    for (x1, y1), (x2, y2) in zip(points, points[1:]):
        total += math.hypot(x2 - x1, y2 - y1)
        cumulative.append(total)
    return cumulative, total


def _normalise_label_angle(angle: float) -> float:
    if angle > 90.0:
        angle -= 180.0
    if angle < -90.0:
        angle += 180.0
    return angle


def _rotated_contour_label(text: str, font: Any, fill: str, angle: float) -> Image.Image:
    dummy = Image.new("RGBA", (1, 1), (255, 255, 255, 0))
    dummy_draw = ImageDraw.Draw(dummy)
    try:
        bbox = dummy_draw.textbbox((0, 0), text, font=font)
    except Exception:
        text_w, text_h = text_size(dummy_draw, text, font)
        bbox = (0, 0, text_w, text_h)
    text_w = max(1, int(math.ceil(bbox[2] - bbox[0])))
    text_h = max(1, int(math.ceil(bbox[3] - bbox[1])))
    pad_x, pad_y = 8, 7
    label = Image.new("RGBA", (text_w + pad_x * 2, text_h + pad_y * 2), (255, 255, 255, 0))
    label_draw = ImageDraw.Draw(label)
    label_draw.text((pad_x - bbox[0], pad_y - bbox[1]), text, font=font, fill=fill)
    resampling = getattr(getattr(Image, "Resampling", Image), "BICUBIC", 3)
    return label.rotate(-angle, expand=True, resample=resampling)


def _boxes_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float], padding: float = 10.0) -> bool:
    return not (a[2] + padding < b[0] or b[2] + padding < a[0] or a[3] + padding < b[1] or b[3] + padding < a[1])


def _contour_label_candidate(
    points: list[tuple[float, float]],
    text: str,
    font: Any,
    clip: tuple[int, int, int, int],
    used_boxes: list[tuple[float, float, float, float]],
) -> dict[str, Any] | None:
    if len(points) < 24:
        return None
    cumulative, total = _polyline_lengths(points)
    if total < 180.0:
        return None
    k = min(7, max(3, len(points) // 16))
    fractions = (0.50, 0.38, 0.62, 0.28, 0.72)
    map_x, map_y, map_w, map_h = clip
    margin = 44.0
    for fraction in fractions:
        target = total * fraction
        idx = min(range(len(cumulative)), key=lambda item: abs(cumulative[item] - target))
        idx = max(k, min(len(points) - k - 1, idx))
        x, y = points[idx]
        if not (map_x + margin < x < map_x + map_w - margin and map_y + margin < y < map_y + map_h - margin):
            continue
        x1, y1 = points[idx - k]
        x2, y2 = points[idx + k]
        dx, dy = x2 - x1, y2 - y1
        if math.hypot(dx, dy) < 1e-6:
            continue
        angle = _normalise_label_angle(math.degrees(math.atan2(dy, dx)))
        image = _rotated_contour_label(text, font, "#516257", angle)
        box_item = (x - image.width / 2, y - image.height / 2, x + image.width / 2, y + image.height / 2)
        if box_item[0] < map_x + 10 or box_item[2] > map_x + map_w - 10 or box_item[1] < map_y + 10 or box_item[3] > map_y + map_h - 10:
            continue
        if any(_boxes_overlap(box_item, other) for other in used_boxes):
            continue
        avg_step = max(total / max(len(points) - 1, 1), 1.0)
        gap_px = max(70.0, min(150.0, image.width + 18.0))
        gap_points = max(4, min(24, int(round((gap_px / 2.0) / avg_step))))
        return {
            "idx": idx,
            "image": image,
            "box": box_item,
            "paste": (int(round(box_item[0])), int(round(box_item[1]))),
            "gap_points": gap_points,
        }
    return None


def _draw_contours(
    canvas: Image.Image,
    raster_data: np.ndarray | None,
    elevation_meta: dict[str, Any],
    bounds_lonlat: tuple[float, float, float, float],
    project: Any,
    clip: tuple[int, int, int, int],
    mostrar_anotaciones: bool = True,
) -> dict[str, Any]:
    classes = elevation_meta.get("elevaciones_clases") or []
    if raster_data is None or not classes or not np.any(np.isfinite(raster_data)):
        return {"curvas_nivel_generadas": False, "n_curvas": 0, "mostrar_anotaciones_curvas_nivel": bool(mostrar_anotaciones), "n_etiquetas_curvas": 0}
    intermediate, main, intermediate_step, main_step = _contour_levels(classes)
    levels = sorted(set(intermediate + main))
    if not levels:
        return {"curvas_nivel_generadas": False, "n_curvas": 0, "mostrar_anotaciones_curvas_nivel": bool(mostrar_anotaciones), "n_etiquetas_curvas": 0}
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        stride = max(1, int(math.ceil(max(raster_data.shape) / 950)))
        data = np.asarray(raster_data[::stride, ::stride], dtype=float)
        fig = plt.figure(figsize=(1, 1))
        ax = fig.add_subplot(111)
        contour = ax.contour(data, levels=levels)
        all_segments = contour.allsegs
        plt.close(fig)
    except Exception as exc:
        return {"curvas_nivel_generadas": False, "n_curvas": 0, "advertencia_curvas": str(exc), "mostrar_anotaciones_curvas_nivel": bool(mostrar_anotaciones), "n_etiquetas_curvas": 0}

    rows, cols = data.shape

    aligned = elevation_meta.get("elevaciones_alineacion") == "reproject_to_webmercator_map_main"

    def rc_to_pixel(col: float, row: float) -> tuple[float, float]:
        if aligned:
            return clip[0] + float(col) * stride, clip[1] + float(row) * stride
        lon_min, lat_min, lon_max, lat_max = bounds_lonlat
        lon = lon_min + (float(col) / max(cols - 1, 1)) * (lon_max - lon_min)
        lat = lat_max - (float(row) / max(rows - 1, 1)) * (lat_max - lat_min)
        return project(lon, lat)

    overlay = Image.new("RGBA", (MAP_WIDTH, MAP_HEIGHT), (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    font_size = 22
    font = pil_font(font_size, bold=False)
    n_curves = 0
    label_count = 0
    label_boxes: list[tuple[float, float, float, float]] = []
    gap_used = False
    for level, segments in zip(levels, all_segments):
        is_main = any(abs(float(level) - edge) < 1e-6 for edge in main)
        color = (72, 105, 88, 92 if is_main else 54)
        width = 3 if is_main else 2
        for segment in segments:
            if len(segment) < 8:
                continue
            projected = [rc_to_pixel(col, row) for col, row in segment]
            label = None
            if mostrar_anotaciones and is_main and label_count < 14:
                label = _contour_label_candidate(projected, f"{level:g} m", font, clip, label_boxes)
            if label:
                idx = int(label["idx"])
                gap_points = int(label["gap_points"])
                gap_start = max(0, idx - gap_points)
                gap_end = min(len(projected) - 1, idx + gap_points)
                if gap_start >= 1:
                    draw_polyline(draw, projected[: gap_start + 1], color, width)
                if gap_end <= len(projected) - 2:
                    draw_polyline(draw, projected[gap_end:], color, width)
                overlay.alpha_composite(label["image"], label["paste"])
                label_boxes.append(label["box"])
                label_count += 1
                gap_used = True
            else:
                draw_polyline(draw, projected, color, width)
            n_curves += 1
    clip_overlay(canvas, overlay, clip)
    return {
        "curvas_nivel_generadas": n_curves > 0,
        "intervalo_clases_elevacion_m": main_step,
        "intervalo_curvas_intermedias": intermediate_step,
        "intervalo_curvas_maestras": main_step,
        "elevaciones_edges": [float(value) for value in main],
        "curvas_main_levels": [float(value) for value in main],
        "curvas_intermediate_levels": [float(value) for value in intermediate],
        "n_curvas": int(n_curves),
        "n_etiquetas_curvas": int(label_count),
        "mostrar_anotaciones_curvas_nivel": bool(mostrar_anotaciones),
        "curvas_etiquetas_sin_halo": bool(mostrar_anotaciones),
        "curvas_etiquetas_rotadas": bool(mostrar_anotaciones),
        "curvas_etiquetas_siguen_tangente": bool(mostrar_anotaciones),
        "curvas_etiquetas_hueco_linea": bool(gap_used),
        "curvas_etiquetas_font_size": int(font_size),
        "curvas_etiquetas_colisiones": "evita solape entre cajas de etiquetas de curvas",
        "curvas_usando_raster_reproyectado": bool(aligned),
        "curvas_raster_stride": int(stride),
    }


def _draw_inset(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    main_bounds: tuple[float, float, float, float],
    admin: tuple[gpd.GeoDataFrame | None, gpd.GeoDataFrame | None],
    basemap_config: dict[str, Any],
    mapa_base: str,
    carto_api_key: str | None,
) -> bool:
    loc_x, loc_y, loc_w, loc_h = MAP_INSET
    draw_inset_frame(draw)
    loc_bounds = overview_bounds_from_main(main_bounds)
    ok = render_report_basemap(loc_bounds, canvas, MAP_INSET, basemap_config, location=True, mapa_base=mapa_base, carto_api_key=carto_api_key)
    loc_project = make_projector(loc_bounds, MAP_INSET)
    overlay = Image.new("RGBA", (MAP_WIDTH, MAP_HEIGHT), (255, 255, 255, 0))
    odraw = ImageDraw.Draw(overlay)
    ccaa, provincias = admin
    draw_admin_boundaries(odraw, ccaa, provincias, loc_project)
    clip_overlay(canvas, overlay, MAP_INSET)
    centre = ((main_bounds[0] + main_bounds[2]) / 2.0, (main_bounds[1] + main_bounds[3]) / 2.0)
    tx, ty = loc_project(*centre)
    radius = max(42, min(72, loc_w * 0.045))
    draw.ellipse((tx - radius, ty - radius, tx + radius, ty + radius), fill=None, outline="#d7191c", width=6)
    draw.line((tx - radius * 0.45, ty, tx + radius * 0.45, ty), fill="#d7191c", width=4)
    draw.line((tx, ty - radius * 0.45, tx, ty + radius * 0.45), fill="#d7191c", width=4)
    draw_inset_outline(draw)
    return ok


def _subtitle(tramo: TramoExtraido) -> list[str]:
    sentido = str(tramo.sentido or "").capitalize()
    return [f"{tramo.carretera} · {sentido}", f"PK {format_pk(tramo.pk_inicio_recorrido)} a {format_pk(tramo.pk_fin_recorrido)}"]


def _finish(
    canvas: Image.Image,
    output_base: Path,
    warnings: list[str],
    timings: dict[str, float],
    base_ok: bool,
    loc_base_ok: bool,
    extra_meta: dict[str, Any] | None = None,
    mapa_base: str = "ign_gris",
) -> tuple[list[Path], dict[str, Any], list[str]]:
    draw = ImageDraw.Draw(canvas)
    draw_output_border(draw)
    paths = [output_base.with_suffix(".png"), output_base.with_suffix(".pdf")]
    stage = perf_counter()
    save_png_rgb(canvas, paths[0])
    save_pdf_rgb(canvas, paths[1])
    timings["exportacion_png_pdf"] = round(perf_counter() - stage, 3)
    if not base_ok:
        warnings.append("Mapa base incompleto o no disponible en mapa principal; se muestra fondo neutro parcial.")
    if not loc_base_ok:
        warnings.append("Mapa base incompleto o no disponible en mapa de situacion; se muestra fondo neutro parcial.")
    if TILE_ERROR_SAMPLES:
        warnings.append("Incidencias de teselas del mapa base: " + " | ".join(TILE_ERROR_SAMPLES[:3]))
    meta = {
        **map_metadata(mapa_base),
        "base_principal_ok": base_ok,
        "base_inset_ok": loc_base_ok,
        "errores_teselas": dict(TILE_ERRORS),
        "tiempos": timings,
    }
    if extra_meta:
        meta.update(extra_meta)
    return paths, meta, warnings


def _prepare_common(
    tramo: TramoExtraido,
    lineas: gpd.GeoDataFrame,
    cols_lineas: dict[str, str | None],
    pks: gpd.GeoDataFrame,
    pk_cols: dict[str, str | None],
    admin: tuple[gpd.GeoDataFrame | None, gpd.GeoDataFrame | None],
    pintar_pks: bool,
    vias_fondo_modo: str = "todas",
    pk_options: dict[str, Any] | None = None,
) -> tuple[Any, gpd.GeoDataFrame, gpd.GeoDataFrame, tuple[gpd.GeoDataFrame | None, gpd.GeoDataFrame | None], tuple[float, float, float, float], Any, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    tramo_geo = _to_4326_geom(tramo.geometry, tramo.crs)
    lineas_geo = _to_4326_gdf(lineas, lineas.crs if lineas is not None and not lineas.empty else tramo.crs)
    pks_geo = _to_4326_gdf(pks, pks.crs if pks is not None and not pks.empty else tramo.crs)
    admin_geo = (
        _to_4326_gdf(admin[0], admin[0].crs if admin and admin[0] is not None and not admin[0].empty else None) if admin and admin[0] is not None else None,
        _to_4326_gdf(admin[1], admin[1].crs if admin and admin[1] is not None and not admin[1].empty else None) if admin and admin[1] is not None else None,
    )
    bounds = fit_bounds_to_clip(_expanded_lonlat_bounds(tramo_geo), MAP_MAIN)
    project = make_projector(bounds, MAP_MAIN)
    roads = _filter_background_roads(_road_records(lineas_geo, cols_lineas, bounds), vias_fondo_modo, tramo.carretera)
    pk_config = _resolve_pk_map_config(tramo, pintar_pks, pk_options)
    pk_items = _pk_items(pks_geo, pk_cols, tramo, bounds, pk_config)
    return tramo_geo, lineas_geo, pks_geo, admin_geo, bounds, project, roads, pk_items, pk_config


def bounds_mapa_principal_lonlat(tramo: TramoExtraido) -> tuple[float, float, float, float]:
    tramo_geo = _to_4326_geom(tramo.geometry, tramo.crs)
    return fit_bounds_to_clip(_expanded_lonlat_bounds(tramo_geo), MAP_MAIN)


def generar_mapa_localizacion(
    tramo: TramoExtraido,
    lineas: gpd.GeoDataFrame,
    cols_lineas: dict[str, str | None],
    pks: gpd.GeoDataFrame,
    pk_cols: dict[str, str | None],
    admin: tuple[gpd.GeoDataFrame | None, gpd.GeoDataFrame | None],
    raster_path: Path | None,
    config: dict[str, Any],
    output_base: Path,
    pintar_pks: bool,
    alpha_elevaciones: float,
    vias_fondo_modo: str = "todas",
    pk_options: dict[str, Any] | None = None,
    mostrar_anotaciones_curvas_nivel: bool = True,
    mapa_base: str = "ign_gris",
    carto_api_key: str | None = None,
    raster_cache: dict[tuple[Any, ...], tuple[np.ndarray | None, dict[str, Any], list[str]]] | None = None,
) -> tuple[list[Path], dict[str, Any], list[str]]:
    warnings: list[str] = []
    timings: dict[str, float] = {}
    stage = perf_counter()
    tramo_geo, _lineas_geo, _pks_geo, admin_geo, bounds, project, roads, pk_items, pk_config = _prepare_common(
        tramo, lineas, cols_lineas, pks, pk_cols, admin, pintar_pks, vias_fondo_modo, pk_options
    )
    timings["preparacion_geometrias_4326"] = round(perf_counter() - stage, 3)

    canvas = new_canvas()
    draw = ImageDraw.Draw(canvas)
    draw_main_frame(draw)
    basemap_config: dict[str, Any] = {"principal": {}, "localizacion": {}}
    stage = perf_counter()
    base_ok = render_report_basemap(bounds, canvas, MAP_MAIN, basemap_config["principal"], location=False, mapa_base=mapa_base, carto_api_key=carto_api_key)
    timings["mapa_base_principal"] = round(perf_counter() - stage, 3)
    stage = perf_counter()
    raster_data, raster_meta, raster_warnings = _prepared_raster_for_map(raster_path, bounds, MAP_MAIN, raster_cache)
    warnings.extend(raster_warnings)
    elevation_meta = _render_elevation_overlay(canvas, raster_data, bounds, MAP_MAIN, alpha_elevaciones, config)
    elevation_meta.update({key: value for key, value in raster_meta.items() if key.startswith("elevaciones_")})
    contour_meta = _draw_contours(canvas, raster_data, elevation_meta, bounds, project, MAP_MAIN, mostrar_anotaciones_curvas_nivel)
    if contour_meta.get("advertencia_curvas"):
        warnings.append(f"No se pudieron generar curvas de nivel: {contour_meta['advertencia_curvas']}")
    timings["elevaciones_curvas"] = round(perf_counter() - stage, 3)
    stage = perf_counter()
    road_segments = _draw_background_roads(canvas, roads, project, MAP_MAIN)
    _draw_study_line(canvas, tramo_geo, project, MAP_MAIN)
    _draw_pks(canvas, pk_items, roads, project, road_segments, MAP_MAIN)
    timings["vias_tramo_pks"] = round(perf_counter() - stage, 3)
    draw_main_outline(draw)
    stage = perf_counter()
    loc_base_ok = _draw_inset(canvas, draw, bounds, admin_geo, basemap_config["localizacion"], mapa_base, carto_api_key)
    timings["inset_mapa_base_admin"] = round(perf_counter() - stage, 3)
    draw_north_arrow(draw)
    draw_scale_bar(draw, bounds)
    legend_y = draw_left_title(draw, "Mapa de localización", _subtitle(tramo))
    rows = [("Tramo de estudio", "#f4a3a8", "line")]
    if elevation_meta.get("elevaciones_renderizadas"):
        rows.append(("Elevaciones", "", "heading"))
        rows.extend((item["label"], item.get("color", "#e5f1e3"), "slope") for item in elevation_meta.get("elevaciones_clases", []))
    draw_legend_rows(draw, legend_y, rows)
    return _finish(
        canvas,
        output_base,
        warnings,
        timings,
        base_ok,
        loc_base_ok,
        {
            "pks_mapa": pk_config,
            "vias_fondo_modo": vias_fondo_modo,
            **raster_meta,
            **elevation_meta,
            **contour_meta,
            "elevaciones_alpha": float(alpha_elevaciones),
            "legend_y_offset_cm": MAP_LEGEND_Y_OFFSET_CM,
            "legend_heading_step_px": MAP_LEGEND_HEADING_STEP_PX,
            "grosor_tramo_anterior": STUDY_LINE_WIDTHS_OLD,
            "grosor_tramo_nuevo": STUDY_LINE_WIDTHS_NEW,
            "mapa_base": basemap_config,
        },
        mapa_base,
    )


def generar_mapa_pendientes(
    tramo: TramoExtraido,
    segmentos: gpd.GeoDataFrame,
    lineas: gpd.GeoDataFrame,
    cols_lineas: dict[str, str | None],
    pks: gpd.GeoDataFrame,
    pk_cols: dict[str, str | None],
    admin: tuple[gpd.GeoDataFrame | None, gpd.GeoDataFrame | None],
    raster_path: Path | None,
    config: dict[str, Any],
    output_base: Path,
    pintar_pks: bool,
    alpha_elevaciones: float,
    vias_fondo_modo: str = "todas",
    pk_options: dict[str, Any] | None = None,
    mostrar_anotaciones_curvas_nivel: bool = True,
    mapa_base: str = "ign_gris",
    carto_api_key: str | None = None,
    raster_cache: dict[tuple[Any, ...], tuple[np.ndarray | None, dict[str, Any], list[str]]] | None = None,
) -> tuple[list[Path], dict[str, Any], list[str]]:
    warnings: list[str] = []
    timings: dict[str, float] = {}
    stage = perf_counter()
    tramo_geo, _lineas_geo, _pks_geo, admin_geo, bounds, project, roads, pk_items, pk_config = _prepare_common(
        tramo, lineas, cols_lineas, pks, pk_cols, admin, pintar_pks, vias_fondo_modo, pk_options
    )
    segmentos_geo = _to_4326_gdf(segmentos, segmentos.crs if segmentos is not None and not segmentos.empty else tramo.crs)
    timings["preparacion_geometrias_4326"] = round(perf_counter() - stage, 3)

    canvas = new_canvas()
    draw = ImageDraw.Draw(canvas)
    draw_main_frame(draw)
    basemap_config: dict[str, Any] = {"principal": {}, "localizacion": {}}
    stage = perf_counter()
    base_ok = render_report_basemap(bounds, canvas, MAP_MAIN, basemap_config["principal"], location=False, mapa_base=mapa_base, carto_api_key=carto_api_key)
    timings["mapa_base_principal"] = round(perf_counter() - stage, 3)
    stage = perf_counter()
    raster_data, raster_meta, raster_warnings = _prepared_raster_for_map(raster_path, bounds, MAP_MAIN, raster_cache)
    warnings.extend(raster_warnings)
    elevation_meta = _render_elevation_overlay(canvas, raster_data, bounds, MAP_MAIN, alpha_elevaciones, config)
    elevation_meta.update({key: value for key, value in raster_meta.items() if key.startswith("elevaciones_")})
    contour_meta = _draw_contours(canvas, raster_data, elevation_meta, bounds, project, MAP_MAIN, mostrar_anotaciones_curvas_nivel)
    if contour_meta.get("advertencia_curvas"):
        warnings.append(f"No se pudieron generar curvas de nivel: {contour_meta['advertencia_curvas']}")
    timings["elevaciones_curvas"] = round(perf_counter() - stage, 3)
    stage = perf_counter()
    road_segments = _draw_background_roads(canvas, roads, project, MAP_MAIN)
    _draw_slope_segments(canvas, tramo_geo, segmentos_geo, project, MAP_MAIN)
    _draw_pks(canvas, pk_items, roads, project, road_segments, MAP_MAIN)
    timings["vias_pendientes_pks"] = round(perf_counter() - stage, 3)
    draw_main_outline(draw)
    stage = perf_counter()
    loc_base_ok = _draw_inset(canvas, draw, bounds, admin_geo, basemap_config["localizacion"], mapa_base, carto_api_key)
    timings["inset_mapa_base_admin"] = round(perf_counter() - stage, 3)
    draw_north_arrow(draw)
    draw_scale_bar(draw, bounds)
    legend_y = draw_left_title(draw, "Mapa de pendientes", _subtitle(tramo))
    used_labels = list(dict.fromkeys(segmentos_geo["clase"].tolist())) if segmentos_geo is not None and len(segmentos_geo) and "clase" in segmentos_geo.columns else []
    classes = [item for item in slope_classes(config) if item["label"] in used_labels] or slope_classes(config)
    elevation_rows: list[tuple[str, str, str]] = []
    if elevation_meta.get("elevaciones_renderizadas"):
        elevation_rows.extend((item["label"], item.get("color", "#e5f1e3"), "slope") for item in elevation_meta.get("elevaciones_clases", []))
    slope_rows = [(item["label"], item["color"], "slope") for item in classes]
    if elevation_rows:
        legend_columns_meta = _draw_two_column_slope_legend(draw, legend_y, elevation_rows, slope_rows)
    else:
        rows: list[tuple[str, str, str]] = [("Pendientes", "", "heading")]
        rows.extend(slope_rows)
        draw_legend_rows(draw, legend_y, rows)
        legend_columns_meta = {"leyenda_pendientes_columnas": 1}
    paths, meta, out_warnings = _finish(
        canvas,
        output_base,
        warnings,
        timings,
        base_ok,
        loc_base_ok,
        {
            "pks_mapa": pk_config,
            "vias_fondo_modo": vias_fondo_modo,
            **raster_meta,
            **elevation_meta,
            **contour_meta,
            "elevaciones_alpha": float(alpha_elevaciones),
            **legend_columns_meta,
            "legend_y_offset_cm": MAP_LEGEND_Y_OFFSET_CM,
            "legend_heading_step_px": MAP_LEGEND_HEADING_STEP_PX,
            "grosor_pendiente_anterior": SLOPE_LINE_WIDTHS_OLD,
            "grosor_pendiente_nuevo": SLOPE_LINE_WIDTHS_NEW,
            "mapa_base": basemap_config,
        },
        mapa_base,
    )
    meta["clases_pendiente"] = classes
    return paths, meta, out_warnings
