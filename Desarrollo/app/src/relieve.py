from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from PIL import Image, ImageColor, ImageDraw
from rasterio.enums import Resampling
from rasterio.transform import from_bounds as transform_from_bounds
from rasterio.warp import reproject, transform_bounds

from .compositor_cartografico_pil import MAP_HEIGHT, MAP_WIDTH, clip_overlay, draw_polyline, pil_font, text_size
from .estilos import elevation_colors, nice_elevation_classes_with_metadata


def _rgba(hex_color: str, alpha: float) -> tuple[int, int, int, int]:
    r, g, b = ImageColor.getrgb(hex_color)
    return r, g, b, max(0, min(255, int(round(float(alpha) * 255))))

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
