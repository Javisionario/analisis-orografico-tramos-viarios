from __future__ import annotations

import math
from pathlib import Path
from time import perf_counter
from typing import Any

import geopandas as gpd
import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import box

from .compositor_cartografico_pil import (
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
    save_pdf_rgb,
    save_png_rgb,
    text_size,
)
from .basemaps import TILE_ERROR_SAMPLES, TILE_ERRORS, render_report_basemap
from .estilos import DIVISION_INTERIOR_PALETTE, slope_classes
from .io_datos import normalize_road_name
from .mapas_render import (
    _draw_background_roads,
    _draw_inset,
    _draw_pks,
    _draw_road_labels,
    _draw_slope_segments,
    _draw_study_line,
    _draw_two_column_slope_legend,
    _expanded_lonlat_bounds,
    _filter_background_roads,
    _finish,
    _pk_items,
    _prepare_common,
    _resolve_pk_map_config,
    _road_label_specs,
    _road_label_style,
    _road_records,
    _subtitle,
    _subtitle_multitramo,
    _to_4326_gdf,
    _to_4326_geom,
    bounds_mapa_principal_lonlat,
    bounds_mapa_principal_multitramo_lonlat,
)
from .relieve import _draw_contours, _prepared_raster_for_map, _render_elevation_overlay
from .tramo import TramoExtraido
from .utils import as_float, format_pk


STUDY_LINE_WIDTHS_OLD = {"borde": 22, "centro": 13}
STUDY_LINE_WIDTHS_NEW = {"borde": 44, "centro": 26}
SLOPE_LINE_WIDTHS_OLD = {"borde": 22, "centro": 13}
SLOPE_LINE_WIDTHS_NEW = {"borde": 44, "centro": 26}



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
    subtramos_geometrias: list[TramoExtraido] | None = None,
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
    parts = [_to_4326_geom(item.geometry, item.crs) for item in (subtramos_geometrias or [])]
    if len(parts) > 1:
        _draw_study_line(canvas, tramo_geo, project, MAP_MAIN, draw_interior=False)
        for index, geometry in enumerate(parts):
            _draw_study_line(canvas, geometry, project, MAP_MAIN, interior=DIVISION_INTERIOR_PALETTE[index % 2], draw_casing=False)
    else:
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
    rows = [("Tramo de estudio", DIVISION_INTERIOR_PALETTE[0], "divided_line" if len(parts) > 1 else "line")]
    if elevation_meta.get("elevaciones_renderizadas"):
        rows.append(("Elevaciones", "", "heading"))
        rows.extend((item["label"], item.get("color", "#e5f1e3"), "slope") for item in elevation_meta.get("elevaciones_clases", []))
    draw_legend_rows(draw, legend_y, rows, divided_palette=DIVISION_INTERIOR_PALETTE)
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
            "divisiones": {"activo": len(parts) > 1, "paleta_interiores": list(DIVISION_INTERIOR_PALETTE) if len(parts) > 1 else []},
        },
        mapa_base,
    )


def generar_mapa_localizacion_multitramo(
    tramos: list[TramoExtraido],
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
    subtitle_entries: list[dict[str, Any]] | None = None,
    mostrar_anotaciones_curvas_nivel: bool = True,
    mapa_base: str = "ign_gris",
    carto_api_key: str | None = None,
    division_geometries: list[list[TramoExtraido]] | None = None,
) -> tuple[list[Path], dict[str, Any], list[str]]:
    """Mapa único de localización para varios scopes ya extraídos."""
    if not tramos:
        raise ValueError("No hay tramos válidos para el mapa de localización.")
    warnings: list[str] = []
    timings: dict[str, float] = {}
    stage = perf_counter()
    tramos_geo = [_to_4326_geom(tramo.geometry, tramo.crs) for tramo in tramos]
    lineas_geo = _to_4326_gdf(lineas, lineas.crs if lineas is not None and not lineas.empty else tramos[0].crs)
    pks_geo = _to_4326_gdf(pks, pks.crs if pks is not None and not pks.empty else tramos[0].crs)
    admin_geo = (
        _to_4326_gdf(admin[0], admin[0].crs if admin[0] is not None and not admin[0].empty else None) if admin[0] is not None else None,
        _to_4326_gdf(admin[1], admin[1].crs if admin[1] is not None and not admin[1].empty else None) if admin[1] is not None else None,
    )
    bounds = bounds_mapa_principal_multitramo_lonlat(tramos)
    project = make_projector(bounds, MAP_MAIN)
    scope_roads = [tramo.carretera for tramo in tramos]
    all_roads = _road_records(lineas_geo, cols_lineas, bounds)
    roads = _filter_background_roads(all_roads, vias_fondo_modo, scope_roads)
    road_label_specs = _road_label_specs(tramos, tramos_geo, all_roads)
    pk_items: list[dict[str, Any]] = []
    configs: list[dict[str, Any]] = []
    for tramo in tramos:
        config_item = _resolve_pk_map_config(tramo, pintar_pks, pk_options)
        configs.append(config_item)
        pk_items.extend(_pk_items(pks_geo, pk_cols, tramo, bounds, config_item))
    unique_items: list[dict[str, Any]] = []
    seen_pks: set[tuple[float, float, float]] = set()
    for item in pk_items:
        key = (round(float(item["lon"]), 7), round(float(item["lat"]), 7), round(float(item["km"]), 4))
        if key not in seen_pks:
            unique_items.append(item)
            seen_pks.add(key)
    timings["preparacion_geometrias_4326"] = round(perf_counter() - stage, 3)

    canvas = new_canvas()
    draw = ImageDraw.Draw(canvas)
    draw_main_frame(draw)
    basemap_config: dict[str, Any] = {"principal": {}, "localizacion": {}}
    stage = perf_counter()
    base_ok = render_report_basemap(bounds, canvas, MAP_MAIN, basemap_config["principal"], location=False, mapa_base=mapa_base, carto_api_key=carto_api_key)
    timings["mapa_base_principal"] = round(perf_counter() - stage, 3)
    stage = perf_counter()
    raster_data, raster_meta, raster_warnings = _prepared_raster_for_map(raster_path, bounds, MAP_MAIN)
    warnings.extend(raster_warnings)
    elevation_meta = _render_elevation_overlay(canvas, raster_data, bounds, MAP_MAIN, alpha_elevaciones, config)
    elevation_meta.update({key: value for key, value in raster_meta.items() if key.startswith("elevaciones_")})
    contour_meta = _draw_contours(canvas, raster_data, elevation_meta, bounds, project, MAP_MAIN, mostrar_anotaciones_curvas_nivel)
    if contour_meta.get("advertencia_curvas"):
        warnings.append(f"No se pudieron generar curvas de nivel: {contour_meta['advertencia_curvas']}")
    timings["elevaciones_curvas"] = round(perf_counter() - stage, 3)
    stage = perf_counter()
    road_segments = _draw_background_roads(canvas, roads, project, MAP_MAIN)
    part_groups = division_geometries or []
    has_divisions = any(len(parts) > 1 for parts in part_groups)
    for index, geometry in enumerate(tramos_geo):
        parts = part_groups[index] if index < len(part_groups) else []
        if len(parts) > 1:
            _draw_study_line(canvas, geometry, project, MAP_MAIN, draw_interior=False)
            for part_index, part in enumerate(parts):
                _draw_study_line(canvas, _to_4326_geom(part.geometry, part.crs), project, MAP_MAIN, interior=DIVISION_INTERIOR_PALETTE[part_index % 2], draw_casing=False)
        else:
            _draw_study_line(canvas, geometry, project, MAP_MAIN)
    road_labels_meta = _draw_road_labels(canvas, road_label_specs, project, MAP_MAIN)
    _draw_pks(canvas, unique_items, roads, project, road_segments, MAP_MAIN)
    timings["vias_tramos_pks"] = round(perf_counter() - stage, 3)
    draw_main_outline(draw)
    stage = perf_counter()
    loc_base_ok = _draw_inset(canvas, draw, bounds, admin_geo, basemap_config["localizacion"], mapa_base, carto_api_key)
    timings["inset_mapa_base_admin"] = round(perf_counter() - stage, 3)
    draw_north_arrow(draw)
    draw_scale_bar(draw, bounds)
    legend_y = draw_left_title(draw, "Mapa de localización", _subtitle_multitramo(subtitle_entries or []))
    rows = [("Tramos de estudio", DIVISION_INTERIOR_PALETTE[0], "divided_line" if has_divisions else "line")]
    if elevation_meta.get("elevaciones_renderizadas"):
        rows.append(("Elevaciones", "", "heading"))
        rows.extend((item["label"], item.get("color", "#e5f1e3"), "slope") for item in elevation_meta.get("elevaciones_clases", []))
    draw_legend_rows(draw, legend_y, rows, divided_palette=DIVISION_INTERIOR_PALETTE)
    return _finish(
        canvas, output_base, warnings, timings, base_ok, loc_base_ok,
        {"pks_mapa": configs, "vias_fondo_modo": vias_fondo_modo, "numero_scopes": len(tramos),
         "tramos_estudio": scope_roads, **raster_meta, **elevation_meta, **contour_meta,
         "elevaciones_alpha": float(alpha_elevaciones), "etiquetas_carretera": road_labels_meta,
         "divisiones": {"activo": has_divisions, "paleta_interiores": list(DIVISION_INTERIOR_PALETTE) if has_divisions else []},
         "mapa_base": basemap_config}, mapa_base,
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
