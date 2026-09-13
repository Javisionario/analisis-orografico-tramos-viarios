from __future__ import annotations

from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, MultiLineString
from shapely.ops import substring

from .estilos import classify_slope, slope_classes
from .tramo import TramoExtraido


def longitud_segmento_auto(longitud_m: float) -> float:
    if longitud_m <= 2000:
        return 100.0
    if longitud_m <= 8000:
        return 200.0
    if longitud_m <= 25000:
        return 500.0
    return 1000.0


def _substring_linear(geometry: Any, start: float, end: float) -> Any:
    if isinstance(geometry, LineString):
        return substring(geometry, start, end)
    if isinstance(geometry, MultiLineString):
        parts = []
        cursor = 0.0
        for part in geometry.geoms:
            part_start = cursor
            part_end = cursor + part.length
            cursor = part_end
            overlap_start = max(start, part_start)
            overlap_end = min(end, part_end)
            if overlap_end <= overlap_start:
                continue
            local_start = overlap_start - part_start
            local_end = overlap_end - part_start
            piece = substring(part, local_start, local_end)
            if not piece.is_empty:
                parts.append(piece)
        if len(parts) == 1:
            return parts[0]
        return MultiLineString(parts)
    return substring(geometry, start, end)


def _segment_values(distances: np.ndarray, values: np.ndarray, start: float, end: float) -> np.ndarray:
    if len(distances) == 0 or len(values) == 0:
        return np.asarray([], dtype=float)
    mask = (distances >= start - 1e-6) & (distances <= end + 1e-6)
    selected = values[mask].astype(float)
    endpoints = np.asarray(
        [
            float(np.interp(start, distances, values)),
            float(np.interp(end, distances, values)),
        ],
        dtype=float,
    )
    return np.concatenate([endpoints, selected])


def _segment_mean(distances: np.ndarray, values: np.ndarray, start: float, end: float) -> float:
    segment = _segment_values(distances, values, start, end)
    finite = segment[np.isfinite(segment)]
    return float(np.nanmean(finite)) if len(finite) else float("nan")


def segmentar_pendientes(
    tramo: TramoExtraido,
    perfil: pd.DataFrame,
    longitud_segmento_m: float | None,
    config: dict[str, Any],
    umbral_pendiente_anomala_pct: float = 20.0,
) -> tuple[gpd.GeoDataFrame, dict[str, Any]]:
    if longitud_segmento_m is None:
        longitud_segmento_m = longitud_segmento_auto(tramo.longitud_m)
    longitud_segmento_m = max(25.0, float(longitud_segmento_m))
    classes = slope_classes(config)
    distances = perfil["distancia_m"].to_numpy(dtype=float)
    pk_values = perfil["pk"].to_numpy(dtype=float)
    z_values = perfil["cota_suavizada_m"].to_numpy(dtype=float)
    if "pendiente_bruta_pct" in perfil.columns:
        slope_raw_values = perfil["pendiente_bruta_pct"].to_numpy(dtype=float)
    elif len(distances) > 1:
        slope_raw_values = np.gradient(z_values, distances) * 100.0
    else:
        slope_raw_values = np.zeros(len(perfil), dtype=float)
    if "pendiente_suavizada_pct" in perfil.columns:
        slope_smoothed_values = perfil["pendiente_suavizada_pct"].to_numpy(dtype=float)
    else:
        slope_smoothed_values = slope_raw_values
    if "pendiente_representada_pct" in perfil.columns:
        slope_represented_values = perfil["pendiente_representada_pct"].to_numpy(dtype=float)
    else:
        slope_represented_values = slope_smoothed_values
    profile_anomalies = perfil["pendiente_anomala"].astype(bool).to_numpy() if "pendiente_anomala" in perfil.columns else np.zeros(len(perfil), dtype=bool)
    rows = []
    start = 0.0
    index = 1
    while start < tramo.longitud_m - 1e-6:
        end = min(start + longitud_segmento_m, tramo.longitud_m)
        z0 = float(np.interp(start, distances, z_values))
        z1 = float(np.interp(end, distances, z_values))
        pk0 = float(np.interp(start, distances, pk_values))
        pk1 = float(np.interp(end, distances, pk_values))
        slope_cota = (z1 - z0) / max(end - start, 1e-9) * 100.0
        profile_mask = (distances >= start - 1e-6) & (distances <= end + 1e-6)
        slope_raw_mean = _segment_mean(distances, slope_raw_values, start, end)
        slope_smoothed_mean = _segment_mean(distances, slope_smoothed_values, start, end)
        slope_represented = _segment_mean(distances, slope_represented_values, start, end)
        if not np.isfinite(slope_represented):
            slope_represented = slope_cota
        anomaly = bool(
            np.any(profile_anomalies[profile_mask])
            or (np.isfinite(slope_smoothed_mean) and abs(slope_smoothed_mean) > float(umbral_pendiente_anomala_pct))
        )
        klass = classify_slope(float(slope_represented), classes)
        geom = _substring_linear(tramo.geometry, start, end)
        rows.append(
            {
                "segmento": index,
                "pk_inicio": pk0,
                "pk_fin": pk1,
                "longitud_m": end - start,
                "cota_inicio_m": z0,
                "cota_fin_m": z1,
                "pendiente_pct": slope_represented,
                "pendiente_bruta_pct": slope_raw_mean,
                "pendiente_bruta_media_pct": slope_raw_mean,
                "pendiente_suavizada_media_pct": slope_smoothed_mean,
                "pendiente_representada_media_pct": slope_represented,
                "pendiente_cota_segmento_pct": slope_cota,
                "pendiente_representada_pct": slope_represented,
                "pendiente_anomala": anomaly,
                "umbral_pendiente_anomala_pct": float(umbral_pendiente_anomala_pct),
                "clase": klass["label"],
                "color": "#ffff00" if anomaly else klass["color"],
                "geometry": geom,
            }
        )
        start = end
        index += 1
    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=tramo.crs)
    meta = {
        "longitud_segmento_m": float(longitud_segmento_m),
        "clases_pendiente": classes,
        "umbral_pendiente_anomala_pct": float(umbral_pendiente_anomala_pct),
        "n_segmentos_anomalos": int(gdf["pendiente_anomala"].sum()) if len(gdf) and "pendiente_anomala" in gdf.columns else 0,
        "criterio_pendiente_mapa": "media por segmento de pendiente_representada_pct procedente del perfil",
        "pendiente_mapa_usa_suavizado_pendientes": True,
        "pendiente_mapa_usa_aplanamiento": True,
    }
    return gdf, meta


def exportar_segmentos(gdf: gpd.GeoDataFrame, output_base: Path) -> list[Path]:
    paths: list[Path] = []
    geojson = output_base.with_suffix(".geojson")
    gpkg = output_base.with_suffix(".gpkg")
    gdf.to_file(geojson, driver="GeoJSON")
    paths.append(geojson)
    gdf.to_file(gpkg, driver="GPKG", layer="segmentos_pendiente")
    paths.append(gpkg)
    return paths
