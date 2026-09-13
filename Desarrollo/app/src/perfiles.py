from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from matplotlib.lines import Line2D
from matplotlib.ticker import AutoMinorLocator, FuncFormatter, MaxNLocator
from rasterio.crs import CRS
from rasterio.warp import transform as transform_coords
from scipy.signal import savgol_filter

from .estilos import resolver_fuente_mpl
from .tramo import TramoExtraido
from .utils import as_float, format_pk


SG_TABLE: dict[int, dict[str, Any]] = {
    0: {"window": 0, "polyorder": 0, "label": "sin suavizado"},
    1: {"window": 3, "polyorder": 4, "label": "efecto muy leve"},
    2: {"window": 5, "polyorder": 3, "label": "leve"},
    3: {"window": 9, "polyorder": 3, "label": "leve-medio"},
    4: {"window": 13, "polyorder": 2, "label": "medio-bajo"},
    5: {"window": 17, "polyorder": 2, "label": "medio"},
    6: {"window": 21, "polyorder": 2, "label": "medio-alto"},
    7: {"window": 27, "polyorder": 2, "label": "alto"},
    8: {"window": 33, "polyorder": 2, "label": "alto estable"},
    9: {"window": 41, "polyorder": 1, "label": "muy alto"},
    10: {"window": 51, "polyorder": 1, "label": "muy suavizado"},
}

PROFILE_ANOMALY_COLOR = "#c2b206"


def _crs_label(crs: Any) -> str | None:
    if crs is None:
        return None
    try:
        return str(CRS.from_user_input(crs))
    except Exception:
        return str(crs)


def _sample_raster(path: Path, xs: np.ndarray, ys: np.ndarray, tramo_crs: Any) -> tuple[np.ndarray, dict[str, Any], list[str]]:
    warnings: list[str] = []
    values: list[float] = []
    meta: dict[str, Any] = {
        "perfil_crs_tramo": _crs_label(tramo_crs),
        "perfil_crs_raster": None,
        "perfil_transformacion_crs_aplicada": False,
        "perfil_n_puntos_muestreo": int(len(xs)),
        "perfil_n_cotas_validas": 0,
    }
    try:
        with rasterio.open(path) as src:
            meta["perfil_crs_raster"] = _crs_label(src.crs)
            sample_xs = xs
            sample_ys = ys
            if src.crs is not None and tramo_crs is not None:
                src_crs = CRS.from_user_input(src.crs)
                geom_crs = CRS.from_user_input(tramo_crs)
                if src_crs != geom_crs:
                    sample_xs_list, sample_ys_list = transform_coords(geom_crs, src_crs, xs.tolist(), ys.tolist())
                    sample_xs = np.asarray(sample_xs_list, dtype=float)
                    sample_ys = np.asarray(sample_ys_list, dtype=float)
                    meta["perfil_transformacion_crs_aplicada"] = True
            elif tramo_crs is None:
                warnings.append("El tramo no tiene CRS; el MDT se muestrea sin transformacion de coordenadas.")
            nodata = src.nodata
            for value in src.sample(list(zip(sample_xs, sample_ys))):
                z = float(value[0])
                if nodata is not None and abs(z - float(nodata)) < 1e-9:
                    z = np.nan
                values.append(z)
    except Exception as exc:
        warnings.append(f"No se pudo muestrear el MDT: {exc}")
        return np.full(len(xs), np.nan), meta, warnings
    arr = np.array(values, dtype=float)
    meta["perfil_n_cotas_validas"] = int(np.count_nonzero(np.isfinite(arr)))
    if np.all(~np.isfinite(arr)):
        warnings.append("El MDT no devolvio cotas validas en el tramo.")
    return arr, meta, warnings


def _sample_pk_z(pks: Any, pk_cols: dict[str, str | None], pk_values: np.ndarray) -> tuple[np.ndarray, list[str]]:
    warnings: list[str] = []
    pk_col = pk_cols.get("pk")
    z_col = pk_cols.get("z")
    if pks is None or not pk_col or not z_col or pk_col not in pks.columns or z_col not in pks.columns:
        return np.full(len(pk_values), np.nan), ["No hay campo de cota en PKs para fallback altimetrico."]
    tmp = pks[[pk_col, z_col]].copy()
    tmp["_pk"] = tmp[pk_col].map(as_float)
    tmp["_z"] = tmp[z_col].map(as_float)
    tmp = tmp.dropna(subset=["_pk", "_z"]).sort_values("_pk")
    if len(tmp) < 2:
        return np.full(len(pk_values), np.nan), ["No hay suficientes PKs con cota para interpolar perfil."]
    arr = np.interp(pk_values, tmp["_pk"].to_numpy(dtype=float), tmp["_z"].to_numpy(dtype=float), left=np.nan, right=np.nan)
    if np.any(~np.isfinite(arr)):
        warnings.append("Parte del perfil queda fuera de las cotas PK disponibles.")
    return arr, warnings


def _fill_nan(values: np.ndarray) -> np.ndarray:
    arr = values.astype(float).copy()
    if np.all(~np.isfinite(arr)):
        return arr
    idx = np.arange(len(arr))
    mask = np.isfinite(arr)
    arr[~mask] = np.interp(idx[~mask], idx[mask], arr[mask])
    return arr


def _valid_sg_window(value: Any, n: int) -> int:
    window = int(round(float(value)))
    window = max(3, min(55, window))
    if window % 2 == 0:
        window += 1 if window < 55 else -1
    max_odd = n if n % 2 == 1 else n - 1
    return max(3, min(window, max_odd))


def _smooth(
    values: np.ndarray,
    smoothing: float,
    intervalo_m: float,
    longitud_m: float,
    mode: str = "simple",
    sg_window_puntos: int | None = None,
    sg_polyorder: int | None = None,
    sg_polyorder_slider_visual: int | None = None,
) -> tuple[np.ndarray, dict[str, Any], list[str]]:
    warnings: list[str] = []
    arr = _fill_nan(values)
    smoothing_mode = str(mode or "simple").strip().lower()
    q = int(round(max(0.0, min(10.0, float(smoothing)))))
    spec = SG_TABLE[q]
    base_meta = {
        "suavizado_modo": "avanzado" if smoothing_mode == "avanzado" else "simple",
        "valor_slider": float(q),
        "suavizado_slider": q,
        "intervalo_muestreo_m": float(intervalo_m),
        "aplicado": False,
        "algoritmo": "sin suavizado",
        "descripcion": spec["label"],
        "sg_window_puntos_teorica": int(spec["window"]),
        "sg_window_puntos_aplicada": 0,
        "sg_window_metros_aprox": 0.0,
        "sg_polyorder": 0,
        "sg_polyorder_slider_visual": sg_polyorder_slider_visual,
        "ventana_m": 0.0,
        "ventana_puntos": 0,
        "polyorder": 0,
    }
    if q == 0 or len(arr) < 3 or np.all(~np.isfinite(arr)):
        if smoothing_mode == "avanzado" and len(arr) >= 3 and np.any(np.isfinite(arr)):
            pass
        else:
            return arr, base_meta, warnings

    d = max(float(intervalo_m), 1e-9)
    if smoothing_mode == "avanzado":
        window = _valid_sg_window(sg_window_puntos or 9, len(arr))
        polyorder = int(round(float(sg_polyorder or 2)))
        polyorder = max(1, min(4, polyorder))
        if polyorder >= window:
            warnings.append(f"Polyorder SG avanzado ({polyorder}) incompatible con ventana {window}; se reduce automaticamente.")
            polyorder = max(1, window - 1)
        smoothed = savgol_filter(arr, window_length=window, polyorder=polyorder, mode="interp")
        return smoothed, {
            **base_meta,
            "aplicado": True,
            "algoritmo": "Savitzky-Golay",
            "descripcion": "avanzado",
            "sg_window_puntos_teorica": int(window),
            "sg_window_puntos_aplicada": int(window),
            "sg_window_metros_aprox": float(window * d),
            "sg_polyorder": int(polyorder),
            "sg_polyorder_slider_visual": sg_polyorder_slider_visual,
            "ventana_m": float(window * d),
            "ventana_puntos": int(window),
            "polyorder": int(polyorder),
        }, warnings

    if q == 0 or len(arr) < 3 or np.all(~np.isfinite(arr)):
        return arr, base_meta, warnings

    window = max(3, int(spec["window"]))
    if window % 2 == 0:
        window += 1
    max_odd = len(arr) if len(arr) % 2 == 1 else len(arr) - 1
    if window > max_odd:
        warnings.append(f"Ventana SG teorica ({window} puntos) reducida a {max_odd} por longitud del tramo.")
        window = max_odd
    if window < 3:
        warnings.append("No se aplica suavizado: numero de puntos insuficiente para ventana minima.")
        return arr, base_meta, warnings
    polyorder = int(spec["polyorder"])
    if polyorder >= window:
        warnings.append(f"Polyorder SG teorico ({polyorder}) incompatible con ventana {window}; se reduce automaticamente.")
        polyorder = max(1, window - 1)
    if polyorder < 1:
        warnings.append("No se aplica suavizado: ventana demasiado pequena.")
        return arr, base_meta, warnings

    smoothed = savgol_filter(arr, window_length=window, polyorder=polyorder, mode="interp")
    return smoothed, {
        **base_meta,
        "valor_slider": float(q),
        "suavizado_slider": q,
        "intervalo_muestreo_m": float(intervalo_m),
        "aplicado": True,
        "algoritmo": "Savitzky-Golay",
        "descripcion": spec["label"],
        "sg_window_puntos_teorica": int(spec["window"]),
        "sg_window_puntos_aplicada": int(window),
        "sg_window_metros_aprox": float(window * d),
        "sg_polyorder": int(polyorder),
        "ventana_m": float(window * d),
        "ventana_puntos": int(window),
        "polyorder": int(polyorder),
    }, warnings


def _sampling_meta(intervalo_m: float, pixel_m: float | None) -> tuple[float, dict[str, Any], list[str]]:
    warnings: list[str] = []
    pixel = float(pixel_m) if pixel_m else None
    intervalo = float(intervalo_m)
    if pixel and intervalo < pixel:
        warnings.append(
            f"Intervalo de muestreo altimetrico ({intervalo:g} m) inferior al tamano de pixel MDT ({pixel:g} m); "
            f"se ajusta a {pixel:g} m para evitar sobremuestreo por debajo de la resolucion real."
        )
        intervalo = pixel
    if pixel and intervalo < 4.0 * pixel:
        warnings.append(
            f"Intervalo de muestreo altimetrico ({intervalo:g} m) inferior al recomendado "
            f"(4 x pixel MDT = {4.0 * pixel:g} m). El perfil puede recoger ruido del raster."
        )
    ratio = intervalo / pixel if pixel and pixel > 0 else None
    meta = {
        "intervalo_muestreo_m": float(intervalo),
        "resolucion_mdt_m": pixel,
        "tamano_pixel_m": pixel,
        "ratio_muestreo_pixel": ratio,
        "ratio_intervalo_pixel": ratio,
        "intervalo_recomendado_min_m": 4.0 * pixel if pixel else None,
    }
    return intervalo, meta, warnings


def _nice_pk_ticks(start: float, end: float, target: int = 6) -> list[float]:
    lo, hi = min(float(start), float(end)), max(float(start), float(end))
    span = hi - lo
    if span <= 0:
        return [float(start)]
    candidates = [0.5, 1, 2, 5, 10, 20, 25, 50, 100]
    step = min(candidates, key=lambda value: abs((span / value) - target))
    for candidate in candidates:
        approx = span / candidate
        if 5 <= approx <= 8:
            step = candidate
            break
    first = np.ceil(lo / step) * step
    ticks: list[float] = []
    value = first
    while value <= hi + step * 0.25:
        ticks.append(round(float(value), 6))
        value += step
    return ticks or [lo, hi]


def _slope_color(value: float) -> str:
    if value <= -4.0:
        return "#2879b9"
    if value < -0.35:
        return "#5fa6d3"
    if value <= 0.35:
        return "#8d969b"
    if value < 4.0:
        return "#df6f66"
    return "#b2182b"


def _apply_slope_anomaly_threshold(slope_smoothed: np.ndarray, threshold_pct: float) -> tuple[np.ndarray, np.ndarray]:
    threshold = max(0.1, float(threshold_pct))
    smoothed = slope_smoothed.astype(float).copy()
    anomalies = np.isfinite(smoothed) & (np.abs(smoothed) > threshold)
    represented = smoothed.copy()
    represented[anomalies] = np.sign(smoothed[anomalies]) * threshold
    return represented, anomalies


def _nice_y_step(span: float) -> float:
    if span <= 0:
        return 10.0
    candidates = [10, 20, 25, 50, 100, 200, 250, 500, 1000]
    return min(candidates, key=lambda value: abs((span / value) - 6))


def _nice_y_axis(values: np.ndarray, mode: str, max_ticks: int = 7) -> dict[str, float | int | str]:
    finite = values[np.isfinite(values)]
    if len(finite) == 0:
        return {
            "modo_eje_y": str(mode),
            "y_min": 0.0,
            "y_min_visual": 0.0,
            "y_tick_min": 0.0,
            "y_tick_max": 10.0,
            "y_max": 1.0,
            "y_tick_step": 10.0,
            "y_tick_count": 2,
            "y_axis_strategy": "nice_steps_max_7_ticks",
        }
    z_min = float(np.nanmin(finite))
    z_max = float(np.nanmax(finite))
    mode_norm = "adaptado" if str(mode).lower() in {"adaptado", "auto", "ajustado"} else "cero"
    candidates = [10, 20, 25, 50, 100, 200, 250, 500, 1000]

    selected: tuple[float, float, float, int] | None = None
    fallback: tuple[float, float, float, int] | None = None
    for step in candidates:
        if mode_norm == "adaptado":
            tick_min = max(0.0, math.floor((z_min - step) / step) * step)
            tick_max = max(step, math.ceil((z_max + step) / step) * step)
        else:
            tick_min = 0.0
            tick_max = max(step, math.ceil((z_max + step) / step) * step)
        if tick_max <= tick_min:
            tick_max = tick_min + step
        count = int(round((tick_max - tick_min) / step)) + 1
        candidate = (float(step), float(tick_min), float(tick_max), int(count))
        if count <= 8 and fallback is None:
            fallback = candidate
        if 4 <= count <= max_ticks:
            selected = candidate
            break
    if selected is None:
        selected = fallback or (float(candidates[-1]), 0.0, float(candidates[-1]), 2)

    step, y_tick_min, y_tick_max, tick_count = selected
    y_min_visual = y_tick_min - step * 0.10 if mode_norm == "cero" and y_tick_min == 0.0 else max(0.0, y_tick_min - step * 0.08)
    y_max = y_tick_max
    return {
        "modo_eje_y": mode_norm,
        "y_min": float(y_min_visual),
        "y_min_visual": float(y_min_visual),
        "y_tick_min": float(y_tick_min),
        "y_tick_max": float(y_tick_max),
        "y_max": float(y_max),
        "y_tick_step": float(step),
        "y_tick_count": int(tick_count),
        "y_axis_strategy": "nice_steps_max_7_ticks",
    }


def _elevation_axis(values: np.ndarray, mode: str) -> dict[str, float | int | str]:
    return _nice_y_axis(values, mode, max_ticks=7)


def _profile_summary(df: pd.DataFrame, y_axis: dict[str, Any], threshold_pct: float) -> dict[str, Any]:
    z = df["cota_suavizada_m"].to_numpy(dtype=float)
    pk = df["pk"].to_numpy(dtype=float)
    slope_repr = df["pendiente_representada_pct"].to_numpy(dtype=float)
    slope_raw = df["pendiente_bruta_pct"].to_numpy(dtype=float)
    slope_smooth = df["pendiente_suavizada_pct"].to_numpy(dtype=float) if "pendiente_suavizada_pct" in df.columns else slope_raw
    anomalies = df["pendiente_anomala"].astype(bool).to_numpy()
    z_finite = np.isfinite(z)
    slope_finite = np.isfinite(slope_repr)
    raw_finite = np.isfinite(slope_raw)
    smooth_finite = np.isfinite(slope_smooth)
    pendiente_media_representada = float(np.nanmean(slope_repr)) if np.any(slope_finite) else None
    pendiente_media_abs = float(np.nanmean(np.abs(slope_repr))) if np.any(slope_finite) else None
    pendiente_media_bruta = float(np.nanmean(slope_raw)) if np.any(raw_finite) else None
    pendiente_media_suavizada = float(np.nanmean(slope_smooth)) if np.any(smooth_finite) else None
    min_z_idx = int(np.nanargmin(np.where(z_finite, z, np.nan))) if np.any(z_finite) else 0
    max_z_idx = int(np.nanargmax(np.where(z_finite, z, np.nan))) if np.any(z_finite) else 0
    min_s_idx = int(np.nanargmin(np.where(slope_finite, slope_repr, np.nan))) if np.any(slope_finite) else 0
    max_s_idx = int(np.nanargmax(np.where(slope_finite, slope_repr, np.nan))) if np.any(slope_finite) else 0
    return {
        "altitud_min_m": float(z[min_z_idx]) if np.any(z_finite) else None,
        "altitud_min_pk": float(pk[min_z_idx]) if len(pk) else None,
        "altitud_max_m": float(z[max_z_idx]) if np.any(z_finite) else None,
        "altitud_max_pk": float(pk[max_z_idx]) if len(pk) else None,
        "rango_altitudinal_m": float(np.nanmax(z) - np.nanmin(z)) if np.any(z_finite) else None,
        "pendiente_max_pct": float(slope_repr[max_s_idx]) if np.any(slope_finite) else None,
        "pendiente_max_pk": float(pk[max_s_idx]) if len(pk) else None,
        "pendiente_min_pct": float(slope_repr[min_s_idx]) if np.any(slope_finite) else None,
        "pendiente_min_pk": float(pk[min_s_idx]) if len(pk) else None,
        "pendiente_media_pct": pendiente_media_representada,
        "pendiente_media_representada_pct": pendiente_media_representada,
        "pendiente_media_suavizada_pct": pendiente_media_suavizada,
        "pendiente_media_abs_pct": pendiente_media_abs,
        "pendiente_media_bruta_pct": pendiente_media_bruta,
        "criterio_calculo_pendiente_media": "pendiente_media_pct y pendiente_media_abs_pct se calculan sobre pendiente_representada_pct; pendiente_media_bruta_pct se conserva como trazabilidad.",
        "pendiente_bruta_max_pct": float(np.nanmax(slope_raw)) if np.any(raw_finite) else None,
        "pendiente_bruta_min_pct": float(np.nanmin(slope_raw)) if np.any(raw_finite) else None,
        "pendiente_suavizada_max_pct": float(np.nanmax(slope_smooth)) if np.any(smooth_finite) else None,
        "pendiente_suavizada_min_pct": float(np.nanmin(slope_smooth)) if np.any(smooth_finite) else None,
        "pendiente_representada_max_pct": float(np.nanmax(slope_repr)) if np.any(slope_finite) else None,
        "pendiente_representada_min_pct": float(np.nanmin(slope_repr)) if np.any(slope_finite) else None,
        "modo_eje_y": y_axis["modo_eje_y"],
        "y_min": y_axis["y_min"],
        "y_min_visual": y_axis["y_min_visual"],
        "y_tick_min": y_axis["y_tick_min"],
        "y_tick_max": y_axis["y_tick_max"],
        "y_max": y_axis["y_max"],
        "y_tick_step": y_axis["y_tick_step"],
        "y_tick_count": y_axis["y_tick_count"],
        "y_axis_strategy": y_axis["y_axis_strategy"],
        "anomalias": {
            "umbral_pendiente_anomala_pct": float(threshold_pct),
            "n_lecturas_anomalas": int(np.count_nonzero(anomalies)),
            "criterio_aplanado": "abs(pendiente_suavizada_pct) > umbral; pendiente_representada_pct = signo * umbral",
            "suavizado_bordes_visual": "El amarillo solo marca tramos con ambos extremos anomalos; los segmentos de transicion conservan el color de pendiente representada.",
        },
    }


def generar_perfil(
    tramo: TramoExtraido,
    raster_path: Path | None,
    pks: Any,
    pk_cols: dict[str, str | None],
    intervalo_m: float | None,
    smoothing: float,
    resolucion_mdt_m: float | None = None,
    umbral_pendiente_anomala_pct: float = 20.0,
    modo_eje_y: str = "cero",
    suavizado_modo: str = "simple",
    sg_window_puntos: int | None = None,
    sg_polyorder: int | None = None,
    sg_polyorder_slider_visual: int | None = None,
    suavizado_pendientes: float = 4.0,
    suavizado_pendientes_modo: str = "simple",
    sg_pendientes_window_puntos: int | None = None,
    sg_pendientes_polyorder: int | None = None,
    sg_pendientes_polyorder_slider_visual: int | None = None,
) -> tuple[pd.DataFrame, dict[str, Any], list[str]]:
    warnings: list[str] = []
    intervalo_base = 75.0 if intervalo_m is None else float(intervalo_m)
    intervalo_m, sampling_meta, sampling_warnings = _sampling_meta(intervalo_base, resolucion_mdt_m)
    warnings.extend(sampling_warnings)

    distances = np.arange(0.0, tramo.longitud_m + intervalo_m, intervalo_m)
    if distances[-1] > tramo.longitud_m:
        distances[-1] = tramo.longitud_m
    distances = np.unique(distances)
    points = [tramo.geometry.interpolate(float(distance)) for distance in distances]
    xs = np.array([point.x for point in points], dtype=float)
    ys = np.array([point.y for point in points], dtype=float)
    fraction = np.divide(distances, max(tramo.longitud_m, 1e-9))
    pk_values = tramo.pk_inicio_recorrido + (tramo.pk_fin_recorrido - tramo.pk_inicio_recorrido) * fraction

    source = "mdt"
    raster_sampling_meta: dict[str, Any] = {
        "perfil_crs_tramo": _crs_label(tramo.crs),
        "perfil_crs_raster": None,
        "perfil_transformacion_crs_aplicada": False,
        "perfil_n_puntos_muestreo": int(len(xs)),
        "perfil_n_cotas_validas": 0,
    }
    if raster_path and raster_path.exists():
        raw_z, raster_sampling_meta, raster_warnings = _sample_raster(raster_path, xs, ys, tramo.crs)
        warnings.extend(raster_warnings)
    else:
        raw_z = np.full(len(xs), np.nan)
        warnings.append("No hay MDT disponible; se intenta fallback con cotas de PK.")
    if np.all(~np.isfinite(raw_z)):
        source = "pk_coord_z"
        raw_z, pk_warnings = _sample_pk_z(pks, pk_cols, pk_values)
        warnings.extend(pk_warnings)
    if np.all(~np.isfinite(raw_z)):
        source = "sin_cota_real"
        raw_z = np.zeros(len(xs), dtype=float)
        warnings.append("No se pudo obtener cota real; se genera perfil plano provisional para no bloquear los demas outputs.")

    sampling_meta.update(raster_sampling_meta)
    smooth_z, elevation_smooth_meta, smooth_warnings = _smooth(
        raw_z,
        smoothing,
        intervalo_m,
        tramo.longitud_m,
        suavizado_modo,
        sg_window_puntos,
        sg_polyorder,
        sg_polyorder_slider_visual,
    )
    warnings.extend(smooth_warnings)
    if len(distances) > 1:
        slope_raw = np.gradient(smooth_z, distances) * 100.0
    else:
        slope_raw = np.zeros(len(distances), dtype=float)
    slope_smoothed, slope_smooth_meta, slope_smooth_warnings = _smooth(
        slope_raw,
        suavizado_pendientes,
        intervalo_m,
        tramo.longitud_m,
        suavizado_pendientes_modo,
        sg_pendientes_window_puntos,
        sg_pendientes_polyorder,
        sg_pendientes_polyorder_slider_visual,
    )
    warnings.extend(slope_smooth_warnings)
    slope_repr, slope_anomaly = _apply_slope_anomaly_threshold(slope_smoothed, umbral_pendiente_anomala_pct)

    df = pd.DataFrame(
        {
            "pk": pk_values,
            "distancia_m": distances,
            "x": xs,
            "y": ys,
            "cota_bruta_m": raw_z,
            "cota_suavizada_m": smooth_z,
            "pendiente_bruta_pct": slope_raw,
            "pendiente_suavizada_pct": slope_smoothed,
            "pendiente_representada_pct": slope_repr,
            "pendiente_perfil_pct": slope_repr,
            "pendiente_anomala": slope_anomaly,
            "umbral_pendiente_anomala_pct": float(umbral_pendiente_anomala_pct),
        }
    )
    y_axis = _elevation_axis(smooth_z, modo_eje_y)
    summary = _profile_summary(df, y_axis, float(umbral_pendiente_anomala_pct))
    meta = {
        "fuente_altimetrica": source,
        "muestreo_altimetrico": sampling_meta,
        "intervalo_muestreo_m": float(intervalo_m),
        "suavizado": elevation_smooth_meta,
        "suavizado_elevaciones": {
            **elevation_smooth_meta,
            "modo": elevation_smooth_meta.get("suavizado_modo"),
            "slider": elevation_smooth_meta.get("suavizado_slider"),
            "descripcion": elevation_smooth_meta.get("descripcion"),
        },
        "suavizado_pendientes": {
            **slope_smooth_meta,
            "modo": slope_smooth_meta.get("suavizado_modo"),
            "slider": slope_smooth_meta.get("suavizado_slider"),
            "descripcion": slope_smooth_meta.get("descripcion"),
        },
        "criterio_calculo_pendiente_bruta": "derivada numerica de cota_suavizada_m",
        "criterio_calculo_pendiente_suavizada": "Savitzky-Golay aplicado a pendiente_bruta_pct",
        **{key: value for key, value in summary.items() if key != "anomalias"},
        "anomalias": summary["anomalias"],
    }
    return df, meta, warnings


def exportar_perfil(
    df: pd.DataFrame,
    output_base: Path,
    mostrar_pendiente: bool,
    tramo: TramoExtraido,
    modo_eje_y: str = "cero",
    mostrar_linea_muestreada_elevaciones: bool = False,
) -> list[Path]:
    paths = [
        output_base.with_suffix(".png"),
        output_base.with_suffix(".pdf"),
        output_base.with_suffix(".svg"),
    ]
    font_name = resolver_fuente_mpl()
    plt.rcParams.update({
        "font.family": font_name,
        "axes.edgecolor": "#25313a",
        "axes.linewidth": 0.85,
    })
    fig, ax = plt.subplots(figsize=(10.8, 4.6), dpi=240)
    x = df["pk"].to_numpy(dtype=float)
    z = df["cota_suavizada_m"].to_numpy(dtype=float)
    raw = df["cota_bruta_m"].to_numpy(dtype=float)
    y_axis = _elevation_axis(z, modo_eje_y)
    zmin = float(y_axis["y_min_visual"])

    ax.fill_between(x, z, zmin, color="#7cad83", alpha=0.32, linewidth=0)
    ax.plot(x, z, color="#255f3c", linewidth=2.0, zorder=3)
    if mostrar_linea_muestreada_elevaciones:
        ax.plot(x, raw, color="#6f8f77", linewidth=0.7, alpha=0.42, zorder=2)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"{value:g} m"))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _pos: format_pk(value)))
    ax.set_xticks(_nice_pk_ticks(float(x[0]), float(x[-1])))
    ax.xaxis.set_minor_locator(AutoMinorLocator(2))
    ax.yaxis.set_minor_locator(AutoMinorLocator(2))
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.grid(True, which="major", color="#9fb0bd", linewidth=0.62, alpha=0.38)
    ax.grid(True, which="minor", color="#d3dce3", linewidth=0.42, alpha=0.42)
    ax.set_facecolor("#fbfcfb")
    fig.patch.set_facecolor("#ffffff")
    ax.set_xlim(float(x[0]), float(x[-1]))
    for label in ax.get_xticklabels():
        label.set_rotation(24)
        label.set_ha("right")
    ax.set_ylim(float(y_axis["y_min_visual"]), float(y_axis["y_max"]))
    ax.set_yticks(np.arange(float(y_axis["y_tick_min"]), float(y_axis["y_tick_max"]) + float(y_axis["y_tick_step"]) * 0.5, float(y_axis["y_tick_step"])))

    fig.text(0.075, 0.965, "Perfil longitudinal", ha="left", va="top", fontsize=14.5, weight="bold", color="#17212b")
    subtitle = f"{tramo.carretera} · {tramo.sentido} · PK {format_pk(tramo.pk_inicio_recorrido)} a {format_pk(tramo.pk_fin_recorrido)}"
    if mostrar_pendiente and "pendiente_representada_pct" in df.columns:
        finite_slope = df["pendiente_representada_pct"].to_numpy(dtype=float)
        finite_slope = finite_slope[np.isfinite(finite_slope)]
        if len(finite_slope):
            mean_abs = float(np.nanmean(np.abs(finite_slope)))
            mean_abs_txt = f"{mean_abs:.1f}".replace(".", ",")
            subtitle = f"{subtitle} · pendiente media abs. {mean_abs_txt} %"
    fig.text(0.075, 0.905, subtitle, ha="left", va="top", fontsize=10.2, color="#526273")

    if mostrar_pendiente:
        ax2 = ax.twinx()
        slope = df["pendiente_representada_pct"].to_numpy(dtype=float) if "pendiente_representada_pct" in df.columns else df["pendiente_perfil_pct"].to_numpy(dtype=float)
        anomalies = df["pendiente_anomala"].astype(bool).to_numpy() if "pendiente_anomala" in df.columns else np.zeros(len(df), dtype=bool)
        for idx in range(max(0, len(x) - 1)):
            if not np.all(np.isfinite([x[idx], x[idx + 1], slope[idx], slope[idx + 1]])):
                continue
            anomalous = bool(anomalies[idx] and anomalies[idx + 1])
            color = PROFILE_ANOMALY_COLOR if anomalous else _slope_color(float(np.nanmean([slope[idx], slope[idx + 1]])))
            ax2.plot(
                [x[idx], x[idx + 1]],
                [slope[idx], slope[idx + 1]],
                color=color,
                linewidth=1.35,
                linestyle="-",
                solid_capstyle="butt",
                clip_on=True,
                zorder=4,
            )
        ax2.set_ylabel("")
        ax2.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"{value:.1f} %"))
        finite = slope[np.isfinite(slope)]
        if len(finite):
            low = float(np.nanpercentile(finite, 5))
            high = float(np.nanpercentile(finite, 95))
            low = min(low, 0.0)
            high = max(high, 0.0)
            if abs(high - low) < 1e-6:
                low -= 1.0
                high += 1.0
            margin = max(0.8, (high - low) * 0.18)
            ax2.set_ylim(low - margin, high + margin)
        ax2.set_xlim(ax.get_xlim())
        ax2.yaxis.set_major_locator(MaxNLocator(nbins=6))

    legend_items = [Line2D([0], [0], color="#255f3c", linewidth=2.2, label="Elevaciones (m)")]
    if mostrar_pendiente:
        legend_items.append(Line2D([0], [0], color="#66717c", linewidth=1.8, linestyle="-", label="Pendientes (%)"))
    if mostrar_linea_muestreada_elevaciones:
        legend_items.append(Line2D([0], [0], color="#6f8f77", linewidth=1.0, alpha=0.7, label="Elevaciones muestreadas (m)"))
    ax.legend(handles=legend_items, loc="center left", bbox_to_anchor=(1.08, 0.5), frameon=False, fontsize=9.2)
    fig.subplots_adjust(left=0.075, right=0.79, top=0.84, bottom=0.18)
    for path in paths:
        fig.savefig(path, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return paths
