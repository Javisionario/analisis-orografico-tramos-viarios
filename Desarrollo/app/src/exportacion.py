from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import geopandas as gpd
import pandas as pd
from rasterio.warp import transform_bounds

from .basemaps import reset_tile_error_state
from .estilos import resolver_fuente_mpl
from .exportacion_soporte import (
    _altimetry_meta,
    _anomaly_ranges,
    _bool,
    _create_zip,
    _division_parts,
    _download_item,
    _expanded_bbox,
    _export_tramo,
    _float_or_none,
    _job_dir,
    _kind_for_file,
    _mark,
    _metadata_params,
    _profile_slug,
    _progress,
    _scope_slug,
    _tramo_calculo_perfil,
    _union_bbox,
    _via_slug,
)
from .exportacion_scope import _run_scope
from .io_datos import load_admin, load_lineas, load_lineas_bbox, load_pks, resolve_road_name
from .mapas import (
    bounds_mapa_principal_lonlat,
    bounds_mapa_principal_multitramo_lonlat,
    generar_mapa_localizacion,
    generar_mapa_localizacion_multitramo,
    generar_mapa_pendientes,
)
from .mdt_wcs import obtener_mdt
from .pendientes import exportar_segmentos, segmentar_pendientes
from .perfil_grafico import exportar_perfil
from .perfiles import calcular_halo_perfil, generar_perfil
from .tramo import TramoError, ajustar_pk_a_rango, extraer_tramo, rango_disponible_sentido
from .subtramos import DivisionError, derivar_subtramos, normalizar_divisiones
from .utils import ensure_dir, format_pk, json_dump, load_config, method_notes, now_slug, parse_interval, resolve_tool_path, slugify




def _single_scope_failure_message(sentido_solicitado: str, errors: list[str]) -> str:
    details = list(dict.fromkeys(errors))
    if str(sentido_solicitado).strip().lower() == "ambos":
        return "No se pudo generar ningún sentido para el tramo solicitado.\n" + "\n".join(f"- {item}" for item in details)
    cause = details[0] if details else "No se pudo determinar la causa."
    return f"No se pudo generar el tramo solicitado.\nCausa:\n{cause}"


def _generar_outputs_single(params: dict[str, Any], progress: Any = None) -> dict[str, Any]:
    config = load_config()
    _progress(progress, 1, "Preparando el tramo de estudio.")
    job_dir = _job_dir(params, config)
    warnings: list[str] = []
    errors: list[str] = []
    timings: dict[str, float] = {}
    metadata_params = _metadata_params(params)
    metadata: dict[str, Any] = {
        "fecha": now_slug(),
        "modo": "single",
        "numero_tramos_solicitados": 1,
        "parametros": metadata_params,
        "notas_metodologicas": method_notes(),
        "advertencias": warnings,
        "errores_no_fatales": errors,
        "tiempos_segundos_por_etapa": timings,
        "fuente_mpl_usada": resolver_fuente_mpl(),
        "scopes": [],
        "tramos": [],
    }
    files: list[Path] = []
    try:
        carretera_raw = str(params.get("carretera", "")).strip()
        carretera = resolve_road_name(config, carretera_raw) or carretera_raw
        if not carretera:
            raise TramoError("Debe indicarse una carretera.")
        pk_inicio = float(params.get("pk_inicio"))
        pk_fin = float(params.get("pk_fin"))
        sentido_solicitado = str(params.get("sentido", "creciente")).strip().lower()
        requested_divisions = list(params.get("divisiones_pk") or [])
        metadata["tramos"].append({
            "indice": 1, "carretera": carretera, "pk_inicio": pk_inicio, "pk_fin": pk_fin, "sentido": sentido_solicitado,
            "divisiones_pk_originales": requested_divisions,
            "divisiones_pk_normalizadas": normalizar_divisiones(pk_inicio, pk_fin, requested_divisions, sentido_solicitado),
            "subtramos_derivados": derivar_subtramos(pk_inicio, pk_fin, requested_divisions, "creciente" if sentido_solicitado == "ambos" else sentido_solicitado),
            "subtramos_derivados_por_sentido": {direction: derivar_subtramos(pk_inicio, pk_fin, requested_divisions, direction) for direction in (["creciente", "decreciente"] if sentido_solicitado == "ambos" else [sentido_solicitado])},
        })
        sentidos = ["creciente", "decreciente"] if sentido_solicitado == "ambos" else [sentido_solicitado]
        metadata["sentido_solicitado"] = sentido_solicitado
        metadata["sentidos_generados"] = []
        metadata["mdt_por_sentido"] = {}
        gen_todo = _bool(params.get("generar_todo"), False)
        generar_localizacion = gen_todo or _bool(params.get("generar_mapa_localizacion"), True)
        generar_pendientes = gen_todo or _bool(params.get("generar_mapa_pendientes"), True)
        generar_perfil_flag = gen_todo or _bool(params.get("generar_perfil"), True)
        generar_datos = gen_todo or _bool(params.get("generar_datos_auxiliares"), True)
        needs_mdt = generar_localizacion or generar_pendientes or generar_perfil_flag or generar_datos
        _progress(progress, 2, "Leyendo carretera y PKs.", carretera)
        stage = perf_counter()
        lineas, cols_lineas, notes = load_lineas(config, carretera)
        warnings.extend(notes)
        _mark(timings, "lectura_capa_tramo", stage)
        stage = perf_counter()
        pks, pk_cols, pk_notes = load_pks(config, carretera)
        warnings.extend(pk_notes)
        _mark(timings, "lectura_pks", stage)
        if lineas.empty:
            raise TramoError(f"No hay carretera {carretera} en la capa configurada.")
        if lineas.crs and getattr(lineas.crs, "is_geographic", False):
            epsg = int(config.get("crs", {}).get("trabajo_epsg", 25830))
            lineas = lineas.to_crs(epsg=epsg)
            pks = pks.to_crs(epsg=epsg)
            warnings.append(f"Los datos estaban en CRS geografico; se reproyectan internamente a EPSG:{epsg}.")
        params["carretera"] = carretera
        metadata_params["carretera"] = carretera
        stage = perf_counter()
        admin = load_admin(config)
        warnings.extend(admin[2])
        _mark(timings, "lectura_limites_admin", stage)
        for sentido_item in sentidos:
            try:
                stage = perf_counter()
                rango_min, rango_max, rango_notes = rango_disponible_sentido(lineas, cols_lineas, sentido_item)
                warnings.extend(rango_notes)
                pk_inicio_ajustado, msg_ini = ajustar_pk_a_rango(pk_inicio, rango_min, rango_max)
                pk_fin_ajustado, msg_fin = ajustar_pk_a_rango(pk_fin, rango_min, rango_max)
                for msg in [msg_ini, msg_fin]:
                    if msg:
                        warnings.append(f"{sentido_item}: {msg}" if sentido_solicitado == "ambos" else msg)
                params_scope = dict(params)
                params_scope["sentido"] = sentido_item
                params_scope["pk_inicio_ajustado"] = pk_inicio_ajustado
                params_scope["pk_fin_ajustado"] = pk_fin_ajustado
                params_scope["_include_sentido_suffix"] = sentido_solicitado == "ambos"
                tramo = extraer_tramo(lineas, cols_lineas, carretera, pk_inicio_ajustado, pk_fin_ajustado, sentido_item, pks, pk_cols)
                divisiones = derivar_subtramos(tramo.pk_inicio_recorrido, tramo.pk_fin_recorrido, params.get("divisiones_pk"), sentido_item)
                params_scope["_divisiones_derivadas"] = divisiones
                params_scope["_division_geometries"] = _division_parts(tramo, lineas, cols_lineas, pks, pk_cols, divisiones)
                warnings.extend(tramo.advertencias)
                _mark(timings, f"extraccion_tramo_{sentido_item}", stage)
                intervalo_perfil = _float_or_none(params.get("intervalo_muestreo_m"))
                if intervalo_perfil is None:
                    intervalo_perfil = float(config.get("perfil", {}).get("intervalo_muestreo_auto_m", 75))
                suavizado_elevaciones_value = params.get("suavizado_elevaciones")
                if suavizado_elevaciones_value in (None, ""):
                    suavizado_elevaciones_value = params.get("suavizado", config.get("perfil", {}).get("suavizado_default", 4))
                elev_mode = str(params.get("suavizado_elevaciones_modo") or params.get("suavizado_modo") or "simple")
                slope_mode = str(params.get("suavizado_pendientes_modo", "simple"))
                elev_window = params.get("sg_elevaciones_window_puntos", params.get("sg_window_puntos"))
                elev_polyorder = params.get("sg_elevaciones_polyorder", params.get("sg_polyorder"))
                slope_window = params.get("sg_pendientes_window_puntos")
                slope_polyorder = params.get("sg_pendientes_polyorder")
                # Antes de conocer la resolución final del WCS se reserva el caso
                # más espaciado soportado (25 m), para que el MDT cubra el halo real.
                intervalo_reserva_mdt = max(float(intervalo_perfil), 25.0)
                halo_reserva = calcular_halo_perfil(
                    tramo.longitud_m,
                    intervalo_reserva_mdt,
                    float(suavizado_elevaciones_value),
                    elev_mode,
                    int(elev_window) if elev_window not in (None, "") else None,
                    int(elev_polyorder) if elev_polyorder not in (None, "") else None,
                    float(params.get("suavizado_pendientes", 4)),
                    slope_mode,
                    int(slope_window) if slope_window not in (None, "") else None,
                    int(slope_polyorder) if slope_polyorder not in (None, "") else None,
                )
                tramo_reserva_mdt = _tramo_calculo_perfil(
                    tramo, lineas, cols_lineas, pks, pk_cols, rango_min, rango_max, float(halo_reserva["halo_m"])
                )
                bbox = _expanded_bbox(
                    tramo.geometry,
                    float(config.get("mapas", {}).get("margen_m_auto", 0.15)),
                    float(config.get("mapas", {}).get("margen_m_min", 250)),
                )
                if generar_localizacion or generar_pendientes:
                    stage = perf_counter()
                    lineas_fondo, cols_fondo, fondo_notes = load_lineas_bbox(config, bbox)
                    warnings.extend(fondo_notes)
                    if lineas_fondo.crs and lineas.crs and lineas_fondo.crs != lineas.crs:
                        lineas_fondo = lineas_fondo.to_crs(lineas.crs)
                    _mark(timings, f"lectura_vias_fondo_bbox_{sentido_item}", stage)
                else:
                    lineas_fondo, cols_fondo = lineas, cols_lineas
                epsg = tramo.crs.to_epsg() if tramo.crs else int(config.get("crs", {}).get("trabajo_epsg", 25830))
                mdt_bbox = bbox
                if generar_localizacion or generar_pendientes:
                    try:
                        map_bounds_lonlat = bounds_mapa_principal_lonlat(tramo)
                        mdt_bbox = tuple(float(v) for v in transform_bounds("EPSG:4326", f"EPSG:{epsg}", *map_bounds_lonlat, densify_pts=21))
                    except Exception as exc:
                        warnings.append(f"No se pudo calcular bbox MDT del encuadre final del mapa; se usa bbox del tramo: {exc}")
                mdt_bbox = _union_bbox(mdt_bbox, tuple(float(value) for value in tramo_reserva_mdt.geometry.bounds))
                if needs_mdt:
                    _progress(progress, 3, "Cargando modelo digital del terreno.", sentido_item)
                    stage = perf_counter()
                    mdt = obtener_mdt(config, mdt_bbox, int(epsg), params.get("resolucion_mdt", "5"))
                    warnings.extend(mdt.warnings)
                    _mark(timings, f"wcs_mdt_cache_{sentido_item}", stage)
                    mdt_meta = {
                        "coverage": mdt.coverage_id,
                        "resolucion_m": mdt.resolution_m,
                        "source": mdt.source,
                        "path": str(mdt.path) if mdt.path else None,
                        "bbox": mdt_bbox,
                        "bbox_origen": "map_main_y_contexto_perfil" if (generar_localizacion or generar_pendientes) else "tramo_y_contexto_perfil",
                        **mdt.metadata,
                    }
                    metadata["mdt_por_sentido"][sentido_item] = mdt_meta
                    metadata["mdt"] = mdt_meta
                    mdt_path = mdt.path
                    mdt_resolution = mdt.resolution_m
                else:
                    mdt_meta = {"source": "no_requerido", "bbox": mdt_bbox}
                    metadata["mdt_por_sentido"][sentido_item] = mdt_meta
                    metadata["mdt"] = mdt_meta
                    mdt_path = None
                    mdt_resolution = None
                intervalo_efectivo = max(float(intervalo_perfil), float(mdt_resolution or 0.0))
                halo_perfil = calcular_halo_perfil(
                    tramo.longitud_m,
                    intervalo_efectivo,
                    float(suavizado_elevaciones_value),
                    elev_mode,
                    int(elev_window) if elev_window not in (None, "") else None,
                    int(elev_polyorder) if elev_polyorder not in (None, "") else None,
                    float(params.get("suavizado_pendientes", 4)),
                    slope_mode,
                    int(slope_window) if slope_window not in (None, "") else None,
                    int(slope_polyorder) if slope_polyorder not in (None, "") else None,
                )
                tramo_calculo_perfil = _tramo_calculo_perfil(
                    tramo, lineas, cols_lineas, pks, pk_cols, rango_min, rango_max, float(halo_perfil["halo_m"])
                )
                params_scope["_mdt_meta"] = mdt_meta
                params_scope["_tramo_calculo_perfil"] = tramo_calculo_perfil
                params_scope["_halo_perfil_puntos"] = int(halo_perfil["halo_puntos"])
                scope_files, scope_meta, scope_warnings = _run_scope(
                    f"TOTAL_{sentido_item}" if sentido_solicitado == "ambos" else "TOTAL",
                    tramo,
                    lineas_fondo,
                    cols_fondo,
                    pks,
                    pk_cols,
                    (admin[0], admin[1]),
                    mdt_path,
                    mdt_resolution,
                    params_scope,
                    config,
                    job_dir,
                    timings,
                    progress,
                )
                files.extend(scope_files)
                warnings.extend(scope_warnings)
                scope_meta["divisiones_pk_originales"] = list(params.get("divisiones_pk") or [])
                scope_meta["divisiones_pk_normalizadas"] = normalizar_divisiones(tramo.pk_inicio_recorrido, tramo.pk_fin_recorrido, params.get("divisiones_pk"), sentido_item)
                scope_meta["subtramos_derivados"] = divisiones
                metadata["scopes"].append(scope_meta)
                metadata["sentidos_generados"].append(sentido_item)
                metadata.setdefault("altimetria_por_sentido", {})[sentido_item] = scope_meta.get("altimetria", {})
                metadata["altimetria"] = scope_meta.get("altimetria", {})
            except Exception as exc:
                msg = f"{sentido_item.capitalize()}: {exc}"
                errors.append(msg)
        if not metadata["scopes"]:
            raise TramoError(_single_scope_failure_message(sentido_solicitado, errors))
    except Exception as exc:
        errors.append(str(exc))
        metadata["estado"] = "error"
        json_dump(job_dir / "metadatos.json", metadata)
        (job_dir / "log.txt").write_text("\n".join(warnings + errors), encoding="utf-8")
        raise

    metadata["estado"] = "ok"
    metadata["advertencias"] = list(dict.fromkeys(warnings))
    metadata["errores_no_fatales"] = errors
    _progress(progress, 9, "Preparando archivos de descarga.")
    stage = perf_counter()
    json_dump(job_dir / "metadatos.json", metadata)
    (job_dir / "log.txt").write_text("\n".join(metadata["advertencias"] + errors), encoding="utf-8")
    files.extend([job_dir / "metadatos.json", job_dir / "log.txt"])
    zip_files = [
        _create_zip(job_dir, files, "mapas", "mapas.zip"),
        _create_zip(job_dir, files, "perfiles", "perfiles.zip"),
        _create_zip(job_dir, files, "datos", "datos_auxiliares.zip"),
    ]
    _mark(timings, "creacion_zips_y_metadatos", stage)
    json_dump(job_dir / "metadatos.json", metadata)
    files.extend(zip_files)
    _progress(progress, 10, "Finalizando resultados.")
    return {
        "job_id": job_dir.name,
        "output_dir": str(job_dir),
        "downloads": [_download_item(job_dir, path) for path in files if path.exists()],
        "zip_downloads": {
            "mapas": _download_item(job_dir, zip_files[0]),
            "perfiles": _download_item(job_dir, zip_files[1]),
            "datos": _download_item(job_dir, zip_files[2]),
        },
        "metadata": metadata,
    }


def _scope_mdt(
    tramo: Any,
    lineas: gpd.GeoDataFrame,
    cols_lineas: dict[str, str | None],
    pks: gpd.GeoDataFrame,
    pk_cols: dict[str, str | None],
    rango_min: float,
    rango_max: float,
    params: dict[str, Any],
    config: dict[str, Any],
) -> tuple[Path | None, float | None, dict[str, Any], Any]:
    """Obtiene el MDT y contexto de perfil para un scope, sin incluir mapas."""
    intervalo = _float_or_none(params.get("intervalo_muestreo_m")) or float(config.get("perfil", {}).get("intervalo_muestreo_auto_m", 75))
    elev_value = params.get("suavizado_elevaciones")
    if elev_value in (None, ""):
        elev_value = params.get("suavizado", config.get("perfil", {}).get("suavizado_default", 4))
    elev_mode = str(params.get("suavizado_elevaciones_modo") or params.get("suavizado_modo") or "simple")
    slope_mode = str(params.get("suavizado_pendientes_modo", "simple"))
    elev_window = params.get("sg_elevaciones_window_puntos", params.get("sg_window_puntos"))
    elev_polyorder = params.get("sg_elevaciones_polyorder", params.get("sg_polyorder"))
    slope_window = params.get("sg_pendientes_window_puntos")
    slope_polyorder = params.get("sg_pendientes_polyorder")
    reserve = calcular_halo_perfil(
        tramo.longitud_m, max(float(intervalo), 25.0), float(elev_value), elev_mode,
        int(elev_window) if elev_window not in (None, "") else None,
        int(elev_polyorder) if elev_polyorder not in (None, "") else None,
        float(params.get("suavizado_pendientes", 4)), slope_mode,
        int(slope_window) if slope_window not in (None, "") else None,
        int(slope_polyorder) if slope_polyorder not in (None, "") else None,
    )
    reserve_tramo = _tramo_calculo_perfil(tramo, lineas, cols_lineas, pks, pk_cols, rango_min, rango_max, float(reserve["halo_m"]))
    bbox = _union_bbox(_expanded_bbox(tramo.geometry), tuple(float(value) for value in reserve_tramo.geometry.bounds))
    epsg = tramo.crs.to_epsg() if tramo.crs else int(config.get("crs", {}).get("trabajo_epsg", 25830))
    mdt = obtener_mdt(config, bbox, int(epsg), params.get("resolucion_mdt", "5"))
    mdt_meta = {
        "coverage": mdt.coverage_id,
        "resolucion_m": mdt.resolution_m,
        "source": mdt.source,
        "path": str(mdt.path) if mdt.path else None,
        "bbox": bbox,
        "bbox_origen": "tramo_y_contexto_perfil",
        **mdt.metadata,
    }
    effective = max(float(intervalo), float(mdt.resolution_m or 0.0))
    halo = calcular_halo_perfil(
        tramo.longitud_m, effective, float(elev_value), elev_mode,
        int(elev_window) if elev_window not in (None, "") else None,
        int(elev_polyorder) if elev_polyorder not in (None, "") else None,
        float(params.get("suavizado_pendientes", 4)), slope_mode,
        int(slope_window) if slope_window not in (None, "") else None,
        int(slope_polyorder) if slope_polyorder not in (None, "") else None,
    )
    profile_tramo = _tramo_calculo_perfil(tramo, lineas, cols_lineas, pks, pk_cols, rango_min, rango_max, float(halo["halo_m"]))
    return mdt.path, mdt.resolution_m, mdt_meta, (profile_tramo, int(halo["halo_puntos"]), list(mdt.warnings))


def _generar_outputs_multitramo(params: dict[str, Any], progress: Any = None) -> dict[str, Any]:
    """Orquesta scopes independientes y un único mapa de localización conjunto."""
    requested = list(params.get("tramos") or [])
    if len(requested) < 2:
        return _generar_outputs_single(params, progress)
    if _bool(params.get("generar_mapa_pendientes"), False) or _bool(params.get("generar_todo"), False):
        raise TramoError("No se pueden generar mapas de pendientes cuando se analizan varios tramos.")
    config = load_config()
    _progress(progress, 1, "Preparando los tramos de estudio.")
    job_dir = _job_dir(params, config)
    warnings: list[str] = []
    errors: list[str] = []
    timings: dict[str, float] = {}
    metadata_params = _metadata_params(params)
    metadata: dict[str, Any] = {
        "fecha": now_slug(), "modo": "multi", "numero_tramos_solicitados": len(requested),
        "tramos_solicitados": requested, "parametros": metadata_params,
        "notas_metodologicas": method_notes(), "advertencias": warnings,
        "errores_no_fatales": errors, "tiempos_segundos_por_etapa": timings,
        "fuente_mpl_usada": resolver_fuente_mpl(), "scopes": [], "mdt_por_scope": {}, "tramos": [],
    }
    files: list[Path] = []
    extracted: list[Any] = []
    combined_pks: list[gpd.GeoDataFrame] = []
    subtitle_entries: list[dict[str, Any]] = []
    extracted_ids: list[str] = []
    division_geometry_groups: list[list[Any]] = []
    try:
        stage = perf_counter()
        admin = load_admin(config)
        warnings.extend(admin[2])
        _mark(timings, "lectura_limites_admin", stage)
        for index, item in enumerate(requested, start=1):
            value = item if isinstance(item, dict) else item.model_dump()
            road_raw = str(value.get("carretera", "")).strip()
            road = resolve_road_name(config, road_raw) or road_raw
            if not road:
                errors.append(f"Tramo {index}: debe indicarse una carretera.")
                continue
            try:
                pk_start, pk_end = float(value.get("pk_inicio")), float(value.get("pk_fin"))
            except (TypeError, ValueError):
                errors.append(f"Tramo {index} · {road}: PK inválido.")
                continue
            requested_direction = str(value.get("sentido", "creciente")).strip().lower()
            try:
                normalized_for_request = normalizar_divisiones(pk_start, pk_end, value.get("divisiones_pk"), requested_direction)
                metadata["tramos"].append({"indice": index, "carretera": road, "pk_inicio": pk_start, "pk_fin": pk_end,
                    "sentido": requested_direction, "divisiones_pk_originales": list(value.get("divisiones_pk") or []),
                    "divisiones_pk_normalizadas": normalized_for_request,
                    "subtramos_derivados": derivar_subtramos(pk_start, pk_end, value.get("divisiones_pk"), "creciente" if requested_direction == "ambos" else requested_direction),
                    "subtramos_derivados_por_sentido": {direction: derivar_subtramos(pk_start, pk_end, value.get("divisiones_pk"), direction) for direction in (["creciente", "decreciente"] if requested_direction == "ambos" else [requested_direction])}})
            except DivisionError as exc:
                errors.append(f"Tramo {index} · {road}: {exc}")
                continue
            try:
                _progress(progress, 2, "Leyendo carretera y PKs.", f"Tramo {index} de {len(requested)} · {road}")
                lineas, cols, notes = load_lineas(config, road)
                pks, pk_cols, pk_notes = load_pks(config, road)
                road_notes = list(notes) + list(pk_notes)
                warnings.extend(f"Tramo {index}: {note}" for note in road_notes)
                if lineas.empty:
                    raise TramoError(f"No hay carretera {road} en la capa configurada.")
                if lineas.crs and getattr(lineas.crs, "is_geographic", False):
                    epsg = int(config.get("crs", {}).get("trabajo_epsg", 25830))
                    lineas, pks = lineas.to_crs(epsg=epsg), pks.to_crs(epsg=epsg)
            except Exception as exc:
                message = f"Tramo {index} · {road}: {exc}"
                errors.append(message)
                warnings.append(message)
                continue
            combined_pks.append(pks)
            directions = ["creciente", "decreciente"] if requested_direction == "ambos" else [requested_direction]
            for direction in directions:
                scope_key = f"T{index:02d}_{direction}"
                try:
                    scope_notes = list(road_notes)
                    low, high, range_notes = rango_disponible_sentido(lineas, cols, direction)
                    scope_notes.extend(range_notes)
                    warnings.extend([f"Tramo {index} · {direction}: {note}" for note in range_notes])
                    adjusted_start, warning_start = ajustar_pk_a_rango(pk_start, low, high)
                    adjusted_end, warning_end = ajustar_pk_a_rango(pk_end, low, high)
                    scope_notes.extend(note for note in (warning_start, warning_end) if note)
                    warnings.extend(f"Tramo {index} · {direction}: {note}" for note in (warning_start, warning_end) if note)
                    tramo = extraer_tramo(lineas, cols, road, adjusted_start, adjusted_end, direction, pks, pk_cols)
                    divisiones = derivar_subtramos(tramo.pk_inicio_recorrido, tramo.pk_fin_recorrido, value.get("divisiones_pk"), direction)
                    scope_notes.extend(tramo.advertencias)
                    warnings.extend(f"Tramo {index} · {direction}: {note}" for note in tramo.advertencias)
                    scope_params = dict(params)
                    scope_params.update({
                        "carretera": road, "pk_inicio": pk_start, "pk_fin": pk_end, "sentido": direction,
                        "generar_mapa_localizacion": False, "generar_mapa_pendientes": False, "generar_todo": False,
                        "_scope_prefix": f"T{index:02d}", "_include_sentido_suffix": requested_direction == "ambos",
                        "_divisiones_derivadas": divisiones,
                        "_division_geometries": _division_parts(tramo, lineas, cols, pks, pk_cols, divisiones),
                    })
                    need_scope_mdt = _bool(scope_params.get("generar_perfil"), True) or _bool(scope_params.get("generar_datos_auxiliares"), False)
                    if need_scope_mdt:
                        _progress(progress, 3, "Cargando modelo digital del terreno.", f"Tramo {index} de {len(requested)} · {road}")
                        mdt_path, mdt_resolution, mdt_meta, profile_context = _scope_mdt(tramo, lineas, cols, pks, pk_cols, low, high, scope_params, config)
                        scope_notes.extend(profile_context[2])
                        warnings.extend(profile_context[2])
                        scope_params["_tramo_calculo_perfil"], scope_params["_halo_perfil_puntos"] = profile_context[:2]
                    else:
                        mdt_path, mdt_resolution, mdt_meta = None, None, {"source": "no_requerido"}
                    scope_params["_mdt_meta"] = mdt_meta
                    scope_files, scope_meta, scope_warnings = _run_scope(
                        scope_key, tramo, lineas, cols, pks, pk_cols, (admin[0], admin[1]),
                        mdt_path, mdt_resolution, scope_params, config, job_dir, timings, progress,
                    )
                    scope_meta["tramo_id"] = f"T{index:02d}"
                    scope_meta["indice_tramo"] = index
                    scope_meta["divisiones_pk_originales"] = list(value.get("divisiones_pk") or [])
                    scope_meta["divisiones_pk_normalizadas"] = normalizar_divisiones(tramo.pk_inicio_recorrido, tramo.pk_fin_recorrido, value.get("divisiones_pk"), direction)
                    scope_meta["subtramos_derivados"] = divisiones
                    scope_meta["advertencias"] = list(dict.fromkeys(scope_notes + list(scope_warnings)))
                    metadata["mdt_por_scope"][scope_key] = mdt_meta
                    metadata["scopes"].append(scope_meta)
                    extracted.append(tramo)
                    extracted_ids.append(f"T{index:02d}")
                    division_geometry_groups.append(scope_params["_division_geometries"])
                    if not any(entry["tramo_id"] == f"T{index:02d}" for entry in subtitle_entries):
                        subtitle_entries.append({
                            "tramo_id": f"T{index:02d}", "original_index": index,
                            "carretera": road, "pk_inicio": pk_start, "pk_fin": pk_end,
                            "sentido": requested_direction,
                        })
                    files.extend(scope_files)
                    warnings.extend(scope_warnings)
                except Exception as exc:
                    message = f"Tramo {index} · {direction}: {exc}"
                    errors.append(message)
                    warnings.append(message)
        if not metadata["scopes"]:
            raise TramoError("No se pudo generar ningún tramo solicitado.")

        if _bool(params.get("generar_mapa_localizacion"), True):
            _progress(progress, 7, "Componiendo mapa de localizacion.", "Tramos de estudio")
            raster_path: Path | None = None
            map_warnings: list[str] = []
            try:
                bounds_lonlat = bounds_mapa_principal_multitramo_lonlat(extracted)
                epsg = extracted[0].crs.to_epsg() if extracted[0].crs else int(config.get("crs", {}).get("trabajo_epsg", 25830))
                map_bbox = tuple(float(v) for v in transform_bounds("EPSG:4326", f"EPSG:{epsg}", *bounds_lonlat, densify_pts=21))
                map_mdt = obtener_mdt(config, map_bbox, int(epsg), params.get("resolucion_mdt", "5"))
                raster_path = map_mdt.path
                map_warnings.extend(map_mdt.warnings)
                metadata["mapa_localizacion_multitramo_mdt"] = {"source": map_mdt.source, "path": str(map_mdt.path) if map_mdt.path else None, "bbox": map_bbox, **map_mdt.metadata}
            except Exception as exc:
                map_warnings.append(f"No se pudo obtener el MDT del mapa conjunto; se omiten elevaciones y curvas: {exc}")
                metadata["mapa_localizacion_multitramo_mdt"] = {"source": "no_disponible", "path": None}
            bboxes = [_expanded_bbox(tramo.geometry) for tramo in extracted]
            lines, line_cols, line_notes = load_lineas_bbox(config, _union_bbox(*bboxes))
            warnings.extend(line_notes)
            if lines.crs and extracted[0].crs and lines.crs != extracted[0].crs:
                lines = lines.to_crs(extracted[0].crs)
            pks_all = gpd.GeoDataFrame(pd.concat(combined_pks, ignore_index=True), geometry="geometry", crs=combined_pks[0].crs)
            map_files, map_meta, generated_warnings = generar_mapa_localizacion_multitramo(
                extracted, lines, line_cols, pks_all, pk_cols, (admin[0], admin[1]), raster_path, config,
                job_dir / "mapa_localizacion_multitramo", _bool(params.get("pintar_pks"), True),
                float(params.get("alpha_elev_localizacion", 0.34)), str(params.get("vias_fondo_modo", "todas")),
                {"modo": params.get("pk_modo", "automatico"), "simbolo_cada_pk": params.get("pk_simbolo_cada"), "etiqueta_cada_pk": params.get("pk_etiqueta_cada")},
                subtitle_entries, _bool(params.get("mostrar_anotaciones_curvas_nivel"), True),
                str(params.get("mapa_base") or config.get("mapas", {}).get("base", "ign_gris")), str(params.get("carto_api_key") or "") or None,
                division_geometries=division_geometry_groups,
            )
            files.extend(map_files)
            warnings.extend(map_warnings + generated_warnings)
            metadata["mapa_localizacion_multitramo"] = map_meta
    except Exception as exc:
        errors.append(str(exc))
        metadata["estado"] = "error"
        json_dump(job_dir / "metadatos.json", metadata)
        (job_dir / "log.txt").write_text("\n".join(warnings + errors), encoding="utf-8")
        raise

    metadata["estado"] = "ok"
    metadata["advertencias"] = list(dict.fromkeys(warnings))
    metadata["errores_no_fatales"] = errors
    _progress(progress, 9, "Preparando archivos de descarga.")
    json_dump(job_dir / "metadatos.json", metadata)
    (job_dir / "log.txt").write_text("\n".join(metadata["advertencias"] + errors), encoding="utf-8")
    files.extend([job_dir / "metadatos.json", job_dir / "log.txt"])
    zip_files = [_create_zip(job_dir, files, "mapas", "mapas.zip"), _create_zip(job_dir, files, "perfiles", "perfiles.zip"), _create_zip(job_dir, files, "datos", "datos_auxiliares.zip")]
    files.extend(zip_files)
    _progress(progress, 10, "Finalizando resultados.")
    return {"job_id": job_dir.name, "output_dir": str(job_dir), "downloads": [_download_item(job_dir, path) for path in files if path.exists()], "zip_downloads": {"mapas": _download_item(job_dir, zip_files[0]), "perfiles": _download_item(job_dir, zip_files[1]), "datos": _download_item(job_dir, zip_files[2])}, "metadata": metadata}


def generar_outputs(params: dict[str, Any], progress: Any = None) -> dict[str, Any]:
    """Despacha el contrato legacy al flujo single y el nuevo al multi."""
    tramos = list(params.get("tramos") or [])
    if len(tramos) > 1:
        return _generar_outputs_multitramo(params, progress)
    params = dict(params)
    if len(tramos) == 1:
        item = tramos[0] if isinstance(tramos[0], dict) else tramos[0].model_dump()
        # El contrato de un tramo sigue el dispatcher single, pero las
        # divisiones son parte de ese tramo y no pueden perderse al elevarlo.
        params.update({key: item.get(key) for key in ("carretera", "pk_inicio", "pk_fin", "sentido", "divisiones_pk")})
    params.setdefault("modo", "single")
    return _generar_outputs_single(params, progress)
