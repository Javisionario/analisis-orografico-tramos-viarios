from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import geopandas as gpd
from rasterio.warp import transform_bounds

from .basemaps import reset_tile_error_state
from .estilos import resolver_fuente_mpl
from .io_datos import load_admin, load_lineas, load_lineas_bbox, load_pks, resolve_road_name
from .mapas import bounds_mapa_principal_lonlat, generar_mapa_localizacion, generar_mapa_pendientes
from .mdt_wcs import obtener_mdt
from .pendientes import exportar_segmentos, segmentar_pendientes
from .perfil_grafico import exportar_perfil
from .perfiles import calcular_halo_perfil, generar_perfil
from .tramo import TramoError, ajustar_pk_a_rango, extraer_tramo, rango_disponible_sentido
from .utils import ensure_dir, format_pk, json_dump, load_config, method_notes, now_slug, parse_interval, resolve_tool_path, slugify


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "si", "s", "yes", "on"}


def _float_or_none(value: Any) -> float | None:
    return parse_interval(value)


def _metadata_params(params: dict[str, Any]) -> dict[str, Any]:
    """Devuelve los parámetros aptos para resultados y metadatos persistentes."""
    return {key: value for key, value in params.items() if key != "carto_api_key"}


def _mark(timings: dict[str, float], name: str, start: float) -> None:
    timings[name] = round(perf_counter() - start, 3)


def _progress(progress: Any, index: int, text: str, detail: str | None = None) -> None:
    if callable(progress):
        progress(index, text, detail)


def _expanded_bbox(geometry: Any, margin_ratio: float = 0.15, min_margin: float = 250.0) -> tuple[float, float, float, float]:
    xmin, ymin, xmax, ymax = geometry.bounds
    size = max(xmax - xmin, ymax - ymin, 1.0)
    margin = max(size * margin_ratio, min_margin)
    return xmin - margin, ymin - margin, xmax + margin, ymax + margin


def _union_bbox(*bboxes: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    return (
        min(bbox[0] for bbox in bboxes),
        min(bbox[1] for bbox in bboxes),
        max(bbox[2] for bbox in bboxes),
        max(bbox[3] for bbox in bboxes),
    )


def _tramo_calculo_perfil(
    tramo: Any,
    lineas: gpd.GeoDataFrame,
    cols_lineas: dict[str, str | None],
    pks: Any,
    pk_cols: dict[str, str | None],
    rango_min: float,
    rango_max: float,
    halo_m: float,
) -> Any:
    """Extrae únicamente el contexto disponible para el cálculo interno."""
    halo_km = max(0.0, float(halo_m)) / 1000.0
    if tramo.sentido == "decreciente":
        pk_inicio = min(float(rango_max), float(tramo.pk_inicio_recorrido) + halo_km)
        pk_fin = max(float(rango_min), float(tramo.pk_fin_recorrido) - halo_km)
    else:
        pk_inicio = max(float(rango_min), float(tramo.pk_inicio_recorrido) - halo_km)
        pk_fin = min(float(rango_max), float(tramo.pk_fin_recorrido) + halo_km)
    return extraer_tramo(lineas, cols_lineas, tramo.carretera, pk_inicio, pk_fin, tramo.sentido, pks, pk_cols)


def _job_dir(params: dict[str, Any], config: dict[str, Any]) -> Path:
    outputs = ensure_dir(resolve_tool_path(config.get("paths", {}).get("outputs", "outputs")))
    carretera = slugify(params.get("carretera"))
    pk_ini = slugify(format_pk(float(params.get("pk_inicio"))))
    pk_fin = slugify(format_pk(float(params.get("pk_fin"))))
    sentido = slugify(params.get("sentido", "creciente"))
    return ensure_dir(outputs / f"{carretera}_PK{pk_ini}-{pk_fin}_{sentido}_{now_slug()}")


def _export_tramo(tramo: Any, output_base: Path, label: str) -> list[Path]:
    gdf = gpd.GeoDataFrame(
        [
            {
                "nombre": label,
                "carretera": tramo.carretera,
                "sentido": tramo.sentido,
                "pk_inicio": tramo.pk_inicio_recorrido,
                "pk_fin": tramo.pk_fin_recorrido,
                "longitud_m": tramo.longitud_m,
                "geometry": tramo.geometry,
            }
        ],
        geometry="geometry",
        crs=tramo.crs,
    )
    geojson = output_base.with_suffix(".geojson")
    gpkg = output_base.with_suffix(".gpkg")
    gdf.to_file(geojson, driver="GeoJSON")
    gdf.to_file(gpkg, driver="GPKG", layer="tramo_estudio")
    return [geojson, gpkg]


def _download_item(job_dir: Path, path: Path) -> dict[str, str]:
    return {
        "name": path.name,
        "url": f"/outputs/{job_dir.name}/{path.name}",
        "path": str(path),
    }


def _kind_for_file(path: Path) -> str:
    name = path.name.lower()
    if name.startswith("mapa_"):
        return "mapas"
    if name.startswith("perfil_longitudinal") or name.startswith("perfil_"):
        return "perfiles"
    return "datos"


def _via_slug(tramo: Any) -> str:
    return slugify(getattr(tramo, "carretera", "tramo"))


def _profile_slug(tramo: Any) -> str:
    return f"{_via_slug(tramo)}_{slugify(getattr(tramo, 'sentido', 'sentido'))}"


def _altimetry_meta(params: dict[str, Any], mdt_meta: dict[str, Any], perfil_meta: dict[str, Any]) -> dict[str, Any]:
    source = str(perfil_meta.get("fuente_altimetrica") or "sin_cota_real")
    if source == "mdt":
        fallback = "No"
        fallback_tipo = None
        display_source = "MDT/WCS"
    elif source == "pk_coord_z":
        fallback = "Si, cotas de PK"
        fallback_tipo = "cotas_pk"
        display_source = "Cotas de PK"
    else:
        fallback = "Si, perfil plano provisional"
        fallback_tipo = "perfil_plano_provisional"
        display_source = "Sin cota real / perfil provisional"
    resolution_used = (
        mdt_meta.get("resolucion_m")
        or mdt_meta.get("resolucion_usada")
        or perfil_meta.get("muestreo_altimetrico", {}).get("resolucion_mdt_m")
    )
    mdt_available = bool(mdt_meta.get("path")) and str(mdt_meta.get("source")) in {"wcs", "cache"}
    return {
        "fuente_altimetrica_usada": source,
        "fuente_altimetrica_usada_label": display_source,
        "resolucion_mdt_solicitada": params.get("resolucion_mdt", "5"),
        "resolucion_mdt_usada": resolution_used,
        "coverage_mdt_usada": mdt_meta.get("coverage") or mdt_meta.get("coverage_usada"),
        "mdt_disponible": mdt_available,
        "estado_mdt": "Disponible" if mdt_available else "No disponible",
        "fallback_altimetrico_aplicado": source != "mdt",
        "fallback_altimetrico": fallback,
        "fallback_altimetrico_tipo": fallback_tipo,
        "mdt_source": mdt_meta.get("source"),
    }


def _anomaly_ranges(perfil: Any, segmentos: Any) -> list[dict[str, Any]]:
    if perfil is None or "pendiente_anomala" not in perfil.columns or "pk" not in perfil.columns:
        return []
    mask = perfil["pendiente_anomala"].astype(bool).to_list()
    pks = perfil["pk"].astype(float).to_list()
    raw_slopes = (
        perfil["pendiente_bruta_pct"].astype(float).to_list()
        if "pendiente_bruta_pct" in perfil.columns
        else [float("nan")] * len(pks)
    )
    smoothed_slopes = (
        perfil["pendiente_suavizada_pct"].astype(float).to_list()
        if "pendiente_suavizada_pct" in perfil.columns
        else raw_slopes
    )
    ranges: list[dict[str, Any]] = []
    start_idx: int | None = None
    for idx, value in enumerate(mask + [False]):
        if value and start_idx is None:
            start_idx = idx
        elif not value and start_idx is not None:
            end_idx = idx - 1
            pk0 = float(pks[start_idx])
            pk1 = float(pks[end_idx])
            range_raw = raw_slopes[start_idx : end_idx + 1]
            range_smoothed = smoothed_slopes[start_idx : end_idx + 1]
            finite_raw = [(local_idx, float(value)) for local_idx, value in enumerate(range_raw) if value == value]
            finite_smoothed = [(local_idx, float(value)) for local_idx, value in enumerate(range_smoothed) if value == value]
            if finite_raw:
                max_local_idx, max_raw_value = max(finite_raw, key=lambda item: abs(item[1]))
                pk_max_raw = float(pks[start_idx + max_local_idx])
                max_raw_abs = abs(max_raw_value)
            else:
                max_raw_value = None
                pk_max_raw = None
                max_raw_abs = None
            if finite_smoothed:
                max_smooth_local_idx, max_smooth_value = max(finite_smoothed, key=lambda item: abs(item[1]))
                pk_max_smooth = float(pks[start_idx + max_smooth_local_idx])
                max_smooth_abs = abs(max_smooth_value)
            else:
                max_smooth_value = None
                pk_max_smooth = None
                max_smooth_abs = None
            n_segments = 0
            if segmentos is not None and len(segmentos) and "pendiente_anomala" in segmentos.columns:
                for _, row in segmentos.iterrows():
                    seg_pk0 = float(row.get("pk_inicio", pk0))
                    seg_pk1 = float(row.get("pk_fin", pk1))
                    if bool(row.get("pendiente_anomala", False)) and max(min(seg_pk0, seg_pk1), min(pk0, pk1)) <= min(max(seg_pk0, seg_pk1), max(pk0, pk1)):
                        n_segments += 1
            ranges.append(
                {
                    "pk_inicio": pk0,
                    "pk_fin": pk1,
                    "n_puntos_muestreo": int(end_idx - start_idx + 1),
                    "n_segmentos_mapa": int(n_segments),
                    "pendiente_bruta_max_abs_pct": max_raw_abs,
                    "pendiente_bruta_max_pct": max_raw_value,
                    "pk_pendiente_bruta_max": pk_max_raw,
                    "pendiente_suavizada_max_abs_pct": max_smooth_abs,
                    "pendiente_suavizada_max_pct": max_smooth_value,
                    "pk_pendiente_suavizada_max": pk_max_smooth,
                }
            )
            start_idx = None
    return ranges


def _create_zip(job_dir: Path, files: list[Path], kind: str, filename: str) -> Path:
    selected = [path for path in files if path.exists() and _kind_for_file(path) == kind and path.suffix.lower() != ".zip"]
    zip_path = job_dir / filename
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as zf:
        for path in selected:
            zf.write(path, arcname=path.name)
    return zip_path


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
    slug = _via_slug(tramo)
    if _bool(params.get("_include_sentido_suffix"), False):
        slug = f"{slug}_{slugify(tramo.sentido)}"
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
        profile_slug = _profile_slug(tramo)
        perfil_con = exportar_perfil(
            perfil,
            job_dir / f"perfil_longitudinal_{profile_slug}_con_pendiente",
            True,
            tramo,
            str(params.get("modo_eje_y", "cero")),
            _bool(params.get("mostrar_linea_muestreada_elevaciones"), False),
        )
        perfil_sin = exportar_perfil(
            perfil,
            job_dir / f"perfil_longitudinal_{profile_slug}_sin_pendiente",
            False,
            tramo,
            str(params.get("modo_eje_y", "cero")),
            _bool(params.get("mostrar_linea_muestreada_elevaciones"), False),
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


def generar_outputs(params: dict[str, Any], progress: Any = None) -> dict[str, Any]:
    config = load_config()
    _progress(progress, 1, "Preparando el tramo de estudio.")
    job_dir = _job_dir(params, config)
    warnings: list[str] = []
    errors: list[str] = []
    timings: dict[str, float] = {}
    metadata_params = _metadata_params(params)
    metadata: dict[str, Any] = {
        "fecha": now_slug(),
        "parametros": metadata_params,
        "notas_metodologicas": method_notes(),
        "advertencias": warnings,
        "errores_no_fatales": errors,
        "tiempos_segundos_por_etapa": timings,
        "fuente_mpl_usada": resolver_fuente_mpl(),
        "scopes": [],
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
                metadata["scopes"].append(scope_meta)
                metadata["sentidos_generados"].append(sentido_item)
                metadata.setdefault("altimetria_por_sentido", {})[sentido_item] = scope_meta.get("altimetria", {})
                metadata["altimetria"] = scope_meta.get("altimetria", {})
            except Exception as exc:
                msg = f"Sentido {sentido_item}: {exc}"
                errors.append(msg)
                warnings.append(msg)
        if not metadata["scopes"]:
            raise TramoError("No se pudo generar ningun sentido para el tramo solicitado.")
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
