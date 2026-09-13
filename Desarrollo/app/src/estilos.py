from __future__ import annotations

from functools import lru_cache
import logging
import math
from typing import Any

import numpy as np

ELEVATION_STEPS = [10, 20, 50, 100, 200, 500]


@lru_cache(maxsize=1)
def resolver_fuente_mpl() -> str:
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
    try:
        from matplotlib import font_manager

        available = {font.name for font in font_manager.fontManager.ttflist}
    except Exception:
        return "DejaVu Sans"
    for candidate in ["Segoe UI", "Arial", "DejaVu Sans"]:
        if candidate in available:
            return candidate
    return "DejaVu Sans"


def _finite_values(values: Any) -> np.ndarray:
    arr = np.asarray(values, dtype=float).ravel()
    return arr[np.isfinite(arr)]


def _elevation_stats(values: Any | None, zmin: float, zmax: float) -> dict[str, Any]:
    if values is not None:
        finite = _finite_values(values)
    else:
        finite = np.asarray([zmin, zmax], dtype=float)
        finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return {}

    raw_min = float(np.min(finite))
    raw_max = float(np.max(finite))
    p02, p05, p95, p98 = (float(v) for v in np.percentile(finite, [2, 5, 95, 98]))
    zero_count = int(np.count_nonzero(np.isclose(finite, 0.0, atol=1e-9)))
    pct_zero = float((zero_count / finite.size) * 100.0)

    class_min = raw_min
    class_max = raw_max
    ignored_zeros = False
    zero_reason = None
    if raw_min <= 0.0 and p05 > 100.0 and pct_zero < 2.0:
        class_min = p02 if p02 > 0.0 else p05
        ignored_zeros = True
        zero_reason = (
            "zmin bruto <= 0, p05 > 100 m y porcentaje de ceros < 2%; "
            "los ceros se ignoran solo para la clasificacion visual."
        )
    elif raw_min <= 0.0:
        zero_reason = "Los ceros se conservan para la clasificacion visual porque parecen parte del rango real."

    return {
        "elevaciones_zmin_raw": raw_min,
        "elevaciones_zmax_raw": raw_max,
        "elevaciones_zmin_clasificacion": float(class_min),
        "elevaciones_zmax_clasificacion": float(class_max),
        "elevaciones_p02": p02,
        "elevaciones_p05": p05,
        "elevaciones_p95": p95,
        "elevaciones_p98": p98,
        "elevaciones_n_pixeles_finitos": int(finite.size),
        "elevaciones_n_pixeles_cero": zero_count,
        "elevaciones_pct_pixeles_cero": round(pct_zero, 4),
        "elevaciones_ceros_ignorados_para_clasificacion": ignored_zeros,
        "elevaciones_motivo_ceros_clasificacion": zero_reason,
    }


def _class_edges(zmin: float, zmax: float, max_classes: int) -> tuple[list[float], float]:
    if zmax < zmin:
        zmin, zmax = zmax, zmin
    if abs(zmax - zmin) < 1e-9:
        step = ELEVATION_STEPS[0]
        start = math.floor(zmin / step) * step
        end = start + step
        return [float(start), float(end)], float(step)

    selected_step = ELEVATION_STEPS[-1]
    selected_start = math.floor(zmin / selected_step) * selected_step
    selected_end = math.ceil(zmax / selected_step) * selected_step
    for candidate in ELEVATION_STEPS:
        start = math.floor(zmin / candidate) * candidate
        end = math.ceil(zmax / candidate) * candidate
        if end <= start:
            end = start + candidate
        n_classes = int(round((end - start) / candidate))
        if n_classes <= max_classes:
            selected_step = candidate
            selected_start = start
            selected_end = end
            break

    edges = []
    value = float(selected_start)
    while value < float(selected_end) - 1e-9:
        edges.append(float(value))
        value += float(selected_step)
    edges.append(float(selected_end))
    return edges, float(selected_step)


def nice_elevation_classes(
    zmin: float,
    zmax: float,
    max_classes: int = 6,
    values: Any | None = None,
) -> list[dict[str, Any]]:
    classes, _meta = nice_elevation_classes_with_metadata(values, zmin=zmin, zmax=zmax, max_classes=max_classes)
    return classes


def nice_elevation_classes_with_metadata(
    values: Any | None = None,
    zmin: float | None = None,
    zmax: float | None = None,
    max_classes: int = 6,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if values is not None:
        finite = _finite_values(values)
        if finite.size == 0:
            return [], {}
        zmin_value = float(np.min(finite)) if zmin is None else float(zmin)
        zmax_value = float(np.max(finite)) if zmax is None else float(zmax)
    else:
        if zmin is None or zmax is None:
            return [], {}
        zmin_value = float(zmin)
        zmax_value = float(zmax)

    if not math.isfinite(zmin_value) or not math.isfinite(zmax_value):
        return [], {}

    stats = _elevation_stats(values, zmin_value, zmax_value)
    if not stats:
        return [], {}
    class_min = float(stats["elevaciones_zmin_clasificacion"])
    class_max = float(stats["elevaciones_zmax_clasificacion"])
    edges, step = _class_edges(class_min, class_max, max(1, int(max_classes)))

    classes = []
    for low, high in zip(edges, edges[1:]):
        classes.append({"min": float(low), "max": float(high), "label": f"{low:g} - {high:g} m"})

    stats.update(
        {
            "elevaciones_step_clase": float(step),
            "elevaciones_start_clase": float(edges[0]) if edges else None,
            "elevaciones_end_clase": float(edges[-1]) if edges else None,
            "elevaciones_n_clases": int(len(classes)),
        }
    )
    return classes, stats


def _legacy_nice_elevation_classes(zmin: float, zmax: float, max_classes: int = 6) -> list[dict[str, Any]]:
    if not math.isfinite(zmin) or not math.isfinite(zmax):
        return []
    if zmax < zmin:
        zmin, zmax = zmax, zmin
    if abs(zmax - zmin) < 1e-9:
        step = 10
    else:
        raw = (zmax - zmin) / max(1, max_classes)
        step = next((candidate for candidate in ELEVATION_STEPS if candidate >= raw), ELEVATION_STEPS[-1])
    start = math.floor(zmin / step) * step
    end = math.ceil(zmax / step) * step
    edges = []
    value = start
    while value < end and len(edges) < max_classes + 1:
        edges.append(value)
        value += step
    if not edges or edges[-1] < end:
        edges.append(end)
    if len(edges) > max_classes + 1:
        step = next((candidate for candidate in ELEVATION_STEPS if candidate >= (end - start) / max_classes), step)
        edges = list(range(int(start), int(end + step), int(step)))
        edges = edges[: max_classes + 1]
        if edges[-1] < end:
            edges[-1] = end
    classes = []
    for low, high in zip(edges, edges[1:]):
        classes.append({"min": float(low), "max": float(high), "label": f"{low:g} - {high:g} m"})
    return classes


def slope_classes(styles: dict[str, Any]) -> list[dict[str, Any]]:
    rows = styles.get("estilos", {}).get("pendientes", {}).get("clases")
    if not rows:
        rows = styles.get("pendientes", {}).get("clases", [])
    result = []
    for low, high, label, color in rows:
        result.append({"min": float(low), "max": float(high), "label": str(label), "color": str(color)})
    return result


def classify_slope(value: float, classes: list[dict[str, Any]]) -> dict[str, Any]:
    for item in classes:
        if float(item["min"]) <= value < float(item["max"]):
            return item
    if classes:
        return classes[0] if value < classes[0]["min"] else classes[-1]
    return {"min": -999, "max": 999, "label": "sin clase", "color": "#999999"}


def elevation_colors(styles: dict[str, Any]) -> list[str]:
    return list(styles.get("estilos", {}).get("elevaciones", {}).get("colores", [])) or [
        "#f8fbf7",
        "#e5f1e3",
        "#c8e3c7",
        "#95cda3",
        "#64b280",
        "#3f8f63",
    ]
