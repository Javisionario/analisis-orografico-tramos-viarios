from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

import geopandas as gpd

from .basemaps import reset_tile_error_state
from .exportacion_soporte import (
    _altimetry_meta,
    _anomaly_ranges,
    _bool,
    _export_tramo,
    _float_or_none,
    _mark,
    _progress,
    _scope_slug,
)
from .mapas import generar_mapa_localizacion, generar_mapa_pendientes
from .pendientes import exportar_segmentos, segmentar_pendientes
from .perfil_grafico import exportar_perfil
from .perfiles import generar_perfil


def _run_scope(
    label: str,
    tramo: Any,
    lineas: Any,
    cols_lineas: dict[str, str | None],
    pks: Any,
    pk_cols: dict[str, str | None],
    admin: tuple[Any, Any],
    raster_path: Path | None,
    mdt_resolution: float | None,
    params: dict[str, Any],
    config: dict[str, Any],
    job_dir: Path,
    timings: dict[str, float],
    progress: Any = None,
) -> tuple[list[Path], dict[str, Any], list[str]]:
    warnings: list[str] = []
    files: list[Path] = []
    slug = _scope_slug(tramo, params)
    generar_todo_flag = _bool(params.get("generar_todo"), False)
    generar_datos = _bool(params.get("generar_datos_auxiliares"), False) or generar_todo_flag
    generar_perfil_flag = _bool(params.get("generar_perfil"), True) or generar_todo_flag
    generar_pendientes_flag = _bool(params.get("generar_mapa_pendientes"), True) or generar_todo_flag
    generar_localizacion_flag = _bool(params.get("generar_mapa_localizacion"), True) or generar_todo_flag
    needs_profile = generar_perfil_flag or generar_pendientes_flag or generar_datos
    needs_segments = generar_pendientes_flag or generar_datos

    perfil = None
    perfil_meta: dict[str, Any] = {}
    segmentos = gpd.GeoDataFrame(geometry=[], crs=tramo.crs)
    seg_meta: dict[str, Any] = {}

    if needs_profile:
        _progress(progress, 4, "Muestreando cotas sobre la via.")
        stage = perf_counter()
        intervalo_m = _float_or_none(params.get("intervalo_muestreo_m"))
        if intervalo_m is None:
            intervalo_m = float(config.get("perfil", {}).get("intervalo_muestreo_auto_m", 75))
        suavizado_elevaciones_value = params.get("suavizado_elevaciones")
        if suavizado_elevaciones_value in (None, ""):
            suavizado_elevaciones_value = params.get("suavizado", config.get("perfil", {}).get("suavizado_default", 4))
        suavizado_elevaciones = float(suavizado_elevaciones_value)
        suavizado_pendientes = float(params.get("suavizado_pendientes", 4))
        elev_mode = str(params.get("suavizado_elevaciones_modo") or params.get("suavizado_modo") or "simple")
        slope_mode = str(params.get("suavizado_pendientes_modo", "simple"))
        perfil, perfil_meta, perfil_warnings = generar_perfil(
            tramo,
            raster_path,
            pks,
            pk_cols,
            intervalo_m,
            suavizado_elevaciones,
            mdt_resolution,
            float(params.get("umbral_pendiente_anomala_pct", 20.0)),
            str(params.get("modo_eje_y", "cero")),
            elev_mode,
            int(params.get("sg_elevaciones_window_puntos", params.get("sg_window_puntos"))) if params.get("sg_elevaciones_window_puntos", params.get("sg_window_puntos")) not in (None, "") else None,
            int(params.get("sg_elevaciones_polyorder", params.get("sg_polyorder"))) if params.get("sg_elevaciones_polyorder", params.get("sg_polyorder")) not in (None, "") else None,
            int(params.get("sg_elevaciones_polyorder_slider_visual", params.get("sg_polyorder_slider_visual"))) if params.get("sg_elevaciones_polyorder_slider_visual", params.get("sg_polyorder_slider_visual")) not in (None, "") else None,
            suavizado_pendientes,
            slope_mode,
            int(params.get("sg_pendientes_window_puntos")) if params.get("sg_pendientes_window_puntos") not in (None, "") else None,
            int(params.get("sg_pendientes_polyorder")) if params.get("sg_pendientes_polyorder") not in (None, "") else None,
            int(params.get("sg_pendientes_polyorder_slider_visual")) if params.get("sg_pendientes_polyorder_slider_visual") not in (None, "") else None,
            tramo_calculo=params.get("_tramo_calculo_perfil"),
            halo_puntos=params.get("_halo_perfil_puntos"),
            divisiones=params.get("_divisiones_derivadas"),
        )
        perfil_meta["mostrar_linea_muestreada_elevaciones"] = _bool(params.get("mostrar_linea_muestreada_elevaciones"), False)
        warnings.extend(perfil_warnings)
        _mark(timings, "perfil_muestreo_suavizado", stage)

    if generar_datos and perfil is not None:
        stage = perf_counter()
        perfil_csv = job_dir / f"datos_auxiliares_{slug}.csv"
        perfil.to_csv(perfil_csv, index=False, encoding="utf-8")
        files.append(perfil_csv)
        _mark(timings, "exportacion_csv_perfil", stage)

    if needs_segments and perfil is not None:
        _progress(progress, 5, "Calculando pendientes.")
        stage = perf_counter()
        seg_len = _float_or_none(params.get("longitud_intervalo_pendiente_m"))
        segmentos, seg_meta = segmentar_pendientes(tramo, perfil, seg_len, config, float(params.get("umbral_pendiente_anomala_pct", 20.0)))
        _mark(timings, "segmentacion_pendientes", stage)

    if generar_perfil_flag and perfil is not None:
        _progress(progress, 6, "Generando perfil longitudinal.")
        stage = perf_counter()
        profile_slug = _scope_slug(tramo, params, profile=True)
        perfil_con = exportar_perfil(
            perfil,
            job_dir / f"perfil_longitudinal_{profile_slug}_con_pendiente",
            True,
            tramo,
            str(params.get("modo_eje_y", "cero")),
            _bool(params.get("mostrar_linea_muestreada_elevaciones"), False),
            params.get("_divisiones_derivadas"),
        )
        perfil_sin = exportar_perfil(
            perfil,
            job_dir / f"perfil_longitudinal_{profile_slug}_sin_pendiente",
            False,
            tramo,
            str(params.get("modo_eje_y", "cero")),
            _bool(params.get("mostrar_linea_muestreada_elevaciones"), False),
            params.get("_divisiones_derivadas"),
        )
        files.extend(perfil_con)
        files.extend(perfil_sin)
        perfil_meta["outputs"] = {
            "perfil_con_pendiente": [str(path) for path in perfil_con],
            "perfil_sin_pendiente": [str(path) for path in perfil_sin],
        }
        _mark(timings, "exportacion_perfil_png_pdf_svg", stage)

    if generar_datos and len(segmentos):
        stage = perf_counter()
        files.extend(exportar_segmentos(segmentos, job_dir / f"datos_auxiliares_{slug}"))
        files.extend(_export_tramo(tramo, job_dir / f"tramo_estudio_{slug}", label))
        _mark(timings, "exportacion_datos_auxiliares_geo", stage)

    map_meta: dict[str, Any] = {}
    pintar_pks = _bool(params.get("pintar_pks"), True)
    pk_options = {
        "modo": params.get("pk_modo", "automatico"),
        "simbolo_cada_pk": params.get("pk_simbolo_cada"),
        "etiqueta_cada_pk": params.get("pk_etiqueta_cada"),
    }
    if str(pk_options["modo"]).strip().lower() == "no_mostrar":
        pintar_pks = False
    vias_fondo_modo = str(params.get("vias_fondo_modo", "todas"))
    mapa_base = str(params.get("mapa_base") or config.get("mapas", {}).get("base", "ign_gris"))
    carto_api_key = str(params.get("carto_api_key") or "") or None
    raster_cache: dict[tuple[Any, ...], tuple[Any, dict[str, Any], list[str]]] = {}
    if generar_localizacion_flag or generar_pendientes_flag:
        reset_tile_error_state()
    if generar_localizacion_flag:
        _progress(progress, 7, "Componiendo mapa de localizacion.")
        stage = perf_counter()
        alpha = float(params.get("alpha_elev_localizacion", 0.34))
        out, meta, map_warnings = generar_mapa_localizacion(
            tramo,
            lineas,
            cols_lineas,
            pks,
            pk_cols,
            admin,
            raster_path,
            config,
            job_dir / f"mapa_localizacion_{slug}",
            pintar_pks,
            alpha,
            vias_fondo_modo,
            pk_options,
            _bool(params.get("mostrar_anotaciones_curvas_nivel"), True),
            mapa_base,
            carto_api_key,
            raster_cache=raster_cache,
            subtramos_geometrias=params.get("_division_geometries"),
        )
        files.extend(out)
        map_meta["localizacion"] = meta
        warnings.extend(map_warnings)
        _mark(timings, "mapa_localizacion", stage)
    if generar_pendientes_flag:
        _progress(progress, 8, "Componiendo mapa de pendientes.")
        stage = perf_counter()
        alpha = float(params.get("alpha_elev_pendientes", 0.46))
        out, meta, map_warnings = generar_mapa_pendientes(
            tramo,
            segmentos,
            lineas,
            cols_lineas,
            pks,
            pk_cols,
            admin,
            raster_path,
            config,
            job_dir / f"mapa_pendientes_{slug}",
            pintar_pks,
            alpha,
            vias_fondo_modo,
            pk_options,
            _bool(params.get("mostrar_anotaciones_curvas_nivel"), True),
            mapa_base,
            carto_api_key,
            raster_cache=raster_cache,
        )
        files.extend(out)
        map_meta["pendientes"] = meta
        warnings.extend(map_warnings)
        _mark(timings, "mapa_pendientes", stage)

    anomaly_meta = dict(perfil_meta.get("anomalias", {}) if isinstance(perfil_meta, dict) else {})
    if seg_meta:
        anomaly_meta["n_segmentos_anomalos"] = seg_meta.get("n_segmentos_anomalos", 0)
    anomaly_meta["detalle_rangos_anomalos"] = _anomaly_ranges(perfil, segmentos)
    mdt_scope_meta = params.get("_mdt_meta") if isinstance(params.get("_mdt_meta"), dict) else {}
    altimetry = _altimetry_meta(params, mdt_scope_meta, perfil_meta)
    pk_map_meta = (
        map_meta.get("localizacion", {}).get("pks_mapa")
        or map_meta.get("pendientes", {}).get("pks_mapa")
        or {}
    )
    map_width_meta = {
        "grosor_tramo_anterior": map_meta.get("localizacion", {}).get("grosor_tramo_anterior"),
        "grosor_tramo_nuevo": map_meta.get("localizacion", {}).get("grosor_tramo_nuevo"),
        "grosor_pendiente_anterior": map_meta.get("pendientes", {}).get("grosor_pendiente_anterior"),
        "grosor_pendiente_nuevo": map_meta.get("pendientes", {}).get("grosor_pendiente_nuevo"),
    }
    meta = {
        "label": label,
        "tramo": {
            "carretera": tramo.carretera,
            "sentido": tramo.sentido,
            "pk_inicio": tramo.pk_inicio_recorrido,
            "pk_fin": tramo.pk_fin_recorrido,
            "longitud_m": tramo.longitud_m,
            **tramo.metadatos,
        },
        "perfil": perfil_meta,
        "altimetria": altimetry,
        "anomalias": anomaly_meta,
        "pendientes": seg_meta,
        "pks_mapa": pk_map_meta,
        "pk_modo": pk_map_meta.get("modo"),
        "simbolo_cada_pk": pk_map_meta.get("simbolo_cada_pk"),
        "etiqueta_cada_pk": pk_map_meta.get("etiqueta_cada_pk"),
        "mostrar_simbolos": pk_map_meta.get("mostrar_simbolos"),
        "mostrar_etiquetas": pk_map_meta.get("mostrar_etiquetas"),
        "longitud_ambito_km": pk_map_meta.get("longitud_ambito_km"),
        "vias_fondo_modo": vias_fondo_modo,
        "grosores_mapa": map_width_meta,
        "mapas": map_meta,
    }
    return files, meta, warnings

