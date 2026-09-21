from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import geopandas as gpd

from .tramo import extraer_tramo
from .utils import ensure_dir, format_pk, now_slug, parse_interval, resolve_tool_path, slugify


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "si", "s", "yes", "on"}


def _float_or_none(value: Any) -> float | None:
    return parse_interval(value)


def _division_parts(tramo: Any, lineas: Any, cols: Any, pks: Any, pk_cols: Any, divisiones: list[dict[str, Any]]) -> list[Any]:
    """Extrae geometrías de presentación; no inicia scopes ni usa MDT."""
    if len(divisiones) <= 1:
        return []
    parts: list[Any] = []
    for item in divisiones:
        parts.append(extraer_tramo(lineas, cols, tramo.carretera, item["pk_inicio"], item["pk_fin"], tramo.sentido, pks, pk_cols))
    return parts


def _metadata_params(params: dict[str, Any]) -> dict[str, Any]:
    """Devuelve los parámetros aptos para resultados y metadatos persistentes."""
    return {key: value for key, value in params.items() if key not in {"carto_api_key", "agrupar_como_subtramos"} and not key.startswith("_")}


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
    tramos = params.get("tramos") or []
    if len(tramos) > 1:
        roads = []
        for item in tramos:
            road = slugify(item.get("carretera") if isinstance(item, dict) else getattr(item, "carretera", ""))
            if road and road not in roads:
                roads.append(road)
        compact_roads = "_".join(roads[:4]) or "TRAMOS"
        return ensure_dir(outputs / f"MULTITRAMO_{len(tramos):02d}_{compact_roads}_{now_slug()}")
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


def _scope_slug(tramo: Any, params: dict[str, Any], profile: bool = False) -> str:
    slug = _profile_slug(tramo) if profile else _via_slug(tramo)
    scope_prefix = str(params.get("_scope_prefix") or "").strip()
    if scope_prefix:
        slug = f"{scope_prefix}_{slug}"
    if not profile and _bool(params.get("_include_sentido_suffix"), False):
        slug = f"{slug}_{slugify(tramo.sentido)}"
    return slug


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
