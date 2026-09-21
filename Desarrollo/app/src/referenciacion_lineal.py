from __future__ import annotations

"""Referenciación lineal basada en la coordenada M original del GeoPackage.

pyogrio/GDAL expone las líneas medidas como XY. Este módulo recupera el WKB
original para conservar M y mantiene juntas la geometría y su calibración.
"""

import math
from typing import Any

from shapely import from_wkb
from shapely.geometry import LineString, MultiLineString, Point


METHOD_GEOMETRY_M = "geometry_m"
METHOD_FALLBACK = "row_bounds_xy_fallback"
_EPSILON = 1e-8


def _gpkg_wkb(blob: bytes) -> bytes | None:
    """Return the WKB payload after the GeoPackage binary header."""
    if len(blob) < 8 or blob[:2] != b"GP":
        return None
    envelope = (blob[3] >> 1) & 0x07
    header = 8 + {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}.get(envelope, 0)
    return blob[header:] if len(blob) > header else None


def measured_parts_from_gpkg(blob: bytes | None) -> list[list[tuple[float, float, float]]]:
    """Read LineStringM/MultiLineStringM coordinates with Shapely's WKB reader."""
    if not blob:
        return []
    payload = _gpkg_wkb(bytes(blob))
    if payload is None:
        return []
    try:
        geometry = from_wkb(payload)
    except Exception:
        return []
    geometries = [geometry] if isinstance(geometry, LineString) else list(geometry.geoms) if isinstance(geometry, MultiLineString) else []
    result: list[list[tuple[float, float, float]]] = []
    for part in geometries:
        coords = list(part.coords)
        # A measured but non-Z WKB is exposed as X/Y/M by Shapely.
        if not getattr(part, "has_m", False) or len(coords) < 2 or any(len(item) < 3 for item in coords):
            return []
        result.append([(float(item[0]), float(item[1]), float(item[-1])) for item in coords])
    return result


def measured_parts(row: Any) -> list[list[tuple[float, float, float]]]:
    parts = row.get("__m_parts") if hasattr(row, "get") else None
    return parts if isinstance(parts, list) else []


def geometry_parts(geometry: Any) -> list[LineString]:
    if isinstance(geometry, LineString) and not geometry.is_empty and geometry.length > 0:
        return [geometry]
    if isinstance(geometry, MultiLineString) and not geometry.is_empty:
        return [part for part in geometry.geoms if not part.is_empty and part.length > 0]
    return []


def _fallback_components(parts: list[LineString], start_m: float, end_m: float) -> list[list[tuple[float, float, float]]]:
    """Create one auditable XY-length fallback across all geometry components."""
    total = sum(float(part.length) for part in parts)
    if total <= _EPSILON:
        return [[] for _ in parts]
    result: list[list[tuple[float, float, float]]] = []
    travelled = 0.0
    for part in parts:
        coords = list(part.coords)
        local = 0.0
        values: list[tuple[float, float, float]] = []
        for index, item in enumerate(coords):
            if index:
                previous = coords[index - 1]
                local += math.hypot(item[0] - previous[0], item[1] - previous[1])
            fraction = (travelled + local) / total
            values.append((float(item[0]), float(item[1]), start_m + (end_m - start_m) * fraction))
        result.append(values)
        travelled += float(part.length)
    return result


def component_coordinates(
    row: Any, geometry: Any, start_m: float, end_m: float
) -> list[tuple[LineString, list[tuple[float, float, float]], str]]:
    """Pair every XY component with its original M coordinates, in source order."""
    parts = geometry_parts(geometry)
    raw_parts = measured_parts(row)
    if len(raw_parts) == len(parts) and all(len(coords) >= 2 for coords in raw_parts):
        return [(part, coords, METHOD_GEOMETRY_M) for part, coords in zip(parts, raw_parts)]
    fallback = _fallback_components(parts, start_m, end_m)
    return [(part, coords, METHOD_FALLBACK) for part, coords in zip(parts, fallback)]


def row_coords(row: Any, geometry: Any, start_m: float, end_m: float) -> tuple[list[tuple[float, float, float]], str]:
    """Compatibility helper for consumers of a single line component."""
    components = component_coordinates(row, geometry, start_m, end_m)
    if len(components) != 1:
        return [], METHOD_FALLBACK
    _part, coords, method = components[0]
    return coords, method


def m_range(coords: list[tuple[float, float, float]]) -> tuple[float, float] | None:
    if len(coords) < 2:
        return None
    values = [item[2] for item in coords]
    return min(values), max(values)


def point_at_m(coords: list[tuple[float, float, float]], value: float) -> Point | None:
    for left, right in zip(coords, coords[1:]):
        low, high = sorted((left[2], right[2]))
        if low - _EPSILON <= value <= high + _EPSILON and abs(right[2] - left[2]) > _EPSILON:
            t = (value - left[2]) / (right[2] - left[2])
            return Point(left[0] + t * (right[0] - left[0]), left[1] + t * (right[1] - left[1]))
    return None


def m_at_point(coords: list[tuple[float, float, float]], point: Point) -> tuple[float, Point, float] | None:
    best: tuple[float, float, Point] | None = None
    for left, right in zip(coords, coords[1:]):
        dx, dy = right[0] - left[0], right[1] - left[1]
        span2 = dx * dx + dy * dy
        if span2 <= _EPSILON:
            continue
        t = max(0.0, min(1.0, ((point.x - left[0]) * dx + (point.y - left[1]) * dy) / span2))
        snapped = Point(left[0] + t * dx, left[1] + t * dy)
        distance = point.distance(snapped)
        if best is None or distance < best[0]:
            best = (distance, left[2] + t * (right[2] - left[2]), snapped)
    return None if best is None else (best[1], best[2], best[0])


def extract_between_m(coords: list[tuple[float, float, float]], start_m: float, end_m: float) -> LineString | None:
    geometry, _calibration = extract_between_m_with_calibration(coords, start_m, end_m)
    return geometry


def extract_between_m_with_calibration(
    coords: list[tuple[float, float, float]], start_m: float, end_m: float
) -> tuple[LineString | None, list[tuple[float, float]]]:
    first, last = point_at_m(coords, start_m), point_at_m(coords, end_m)
    if first is None or last is None:
        return None, []
    low, high = sorted((start_m, end_m))
    middle = [(x, y, m) for x, y, m in coords if low < m < high]
    if start_m > end_m:
        middle.reverse()
    selected = [(first.x, first.y, start_m), *middle, (last.x, last.y, end_m)]
    geometry = LineString([(x, y) for x, y, _m in selected])
    distance = 0.0
    calibration = [(0.0, selected[0][2])]
    for left, right in zip(selected, selected[1:]):
        distance += math.hypot(right[0] - left[0], right[1] - left[1])
        calibration.append((distance, right[2]))
    return geometry, calibration


def m_at_distance(calibration: list[tuple[float, float]], distance: float, tolerance: float = 1e-6) -> float:
    """Return M at distance, refusing an out-of-range extrapolation."""
    if len(calibration) < 2:
        raise ValueError("No hay calibración distancia-M suficiente.")
    first_d, first_m = calibration[0]
    last_d, last_m = calibration[-1]
    if distance < first_d - tolerance or distance > last_d + tolerance:
        raise ValueError("Distancia fuera del intervalo calibrado.")
    if distance <= first_d + tolerance:
        return first_m
    if distance >= last_d - tolerance:
        return last_m
    for (d0, m0), (d1, m1) in zip(calibration, calibration[1:]):
        if d0 - tolerance <= distance <= d1 + tolerance and d1 > d0:
            return m0 + (m1 - m0) * (distance - d0) / (d1 - d0)
    raise ValueError("La calibración distancia-M contiene un hueco.")
