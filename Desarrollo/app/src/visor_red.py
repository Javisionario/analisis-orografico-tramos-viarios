from __future__ import annotations

"""Spatial operations for the interactive calibrated-road viewer.

All calibration is performed in the source layer CRS (or a local metric CRS
when the source happens to be geographic); only API boundaries use WGS84.
"""

from dataclasses import dataclass
from typing import Any

import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge, substring, unary_union

from .tramo import m_values
from .utils import as_float


class VisorRedError(ValueError):
    pass


@dataclass
class PuntoCalibrado:
    carretera: str
    pk: float
    snapped: Point
    distancia_m: float
    row_index: Any
    branch: str
    crs: Any


def is_autovia(carretera: Any, tipo_via: Any) -> bool:
    text = f"{carretera or ''} {tipo_via or ''}".lower()
    return any(token in text for token in ("autov", "autop", "motorway", "dual"))


def _metric_source(lineas: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if lineas.crs is None:
        raise VisorRedError("La capa de vías no declara un CRS.")
    if not lineas.crs.is_geographic:
        return lineas
    metric_crs = lineas.estimate_utm_crs()
    if metric_crs is None:
        raise VisorRedError("No se pudo determinar un CRS métrico para la capa.")
    return lineas.to_crs(metric_crs)


def _valid_line(geometry: Any) -> LineString | None:
    if isinstance(geometry, LineString) and not geometry.is_empty and geometry.length > 0:
        return geometry
    if isinstance(geometry, MultiLineString) and not geometry.is_empty:
        merged = linemerge(geometry)
        if isinstance(merged, LineString) and merged.length > 0:
            return merged
    return None


def _row_pk_bounds(row: Any, m0: str, m1: str, scale: float) -> tuple[float, float] | None:
    start, end = as_float(row.get(m0)), as_float(row.get(m1))
    if start is None or end is None:
        return None
    return float(start * scale / 1000.0), float(end * scale / 1000.0)


def _branch_value(row: Any, cols: dict[str, str | None], index: Any) -> str:
    direction = cols.get("sentido")
    if direction and direction in row.index and row.get(direction) is not None:
        return str(row.get(direction))
    return f"row:{index}"


def _prefer_key(row: Any, index: Any) -> tuple[int, str]:
    original = str(row.get("ORIGINAL", "")).upper()
    return (0 if original in {"SI", "1", "TRUE"} else 1, str(index))


def punto_a_pk(
    lineas: gpd.GeoDataFrame, cols: dict[str, str | None], point: Point, tolerance_m: float
) -> list[PuntoCalibrado]:
    """Snap a metric point to each plausible calibrated segment."""
    source = _metric_source(lineas)
    road_col = cols.get("carretera")
    if not road_col:
        raise VisorRedError("No se detectó el campo de carretera.")
    m0, m1, scale = m_values(source, cols)
    candidates: list[PuntoCalibrado] = []
    for index, row in source.iterrows():
        geometry = _valid_line(row.geometry)
        bounds = _row_pk_bounds(row, m0, m1, scale)
        if geometry is None or bounds is None or not row.get(road_col):
            continue
        position = geometry.project(point)
        snapped = geometry.interpolate(position)
        distance = point.distance(snapped)
        if distance > tolerance_m:
            continue
        fraction = position / geometry.length
        pk = bounds[0] + fraction * (bounds[1] - bounds[0])
        candidates.append(
            PuntoCalibrado(str(row[road_col]), float(pk), snapped, float(distance), index, _branch_value(row, cols, index), source.crs)
        )
    return candidates


def localizar_pk(lineas: gpd.GeoDataFrame, cols: dict[str, str | None], carretera: str, pk: float) -> PuntoCalibrado:
    source = _metric_source(lineas)
    road_col = cols.get("carretera")
    if not road_col:
        raise VisorRedError("No se detectó el campo de carretera.")
    m0, m1, scale = m_values(source, cols)
    matches: list[tuple[tuple[int, str], PuntoCalibrado]] = []
    for index, row in source.iterrows():
        if str(row.get(road_col)) != carretera:
            continue
        geometry = _valid_line(row.geometry)
        bounds = _row_pk_bounds(row, m0, m1, scale)
        if geometry is None or bounds is None:
            continue
        low, high = sorted(bounds)
        if not low - 1e-9 <= pk <= high + 1e-9 or abs(bounds[1] - bounds[0]) < 1e-12:
            continue
        fraction = (float(pk) - bounds[0]) / (bounds[1] - bounds[0])
        snapped = geometry.interpolate(max(0.0, min(1.0, fraction)) * geometry.length)
        matches.append((_prefer_key(row, index), PuntoCalibrado(carretera, float(pk), snapped, 0.0, index, _branch_value(row, cols, index), source.crs)))
    if not matches:
        raise VisorRedError(f"El PK indicado no está calibrado en {carretera}.")
    return min(matches, key=lambda item: item[0])[1]


def agrupar_candidatos(candidates: list[PuntoCalibrado]) -> dict[str, list[PuntoCalibrado]]:
    grouped: dict[str, list[PuntoCalibrado]] = {}
    for item in candidates:
        grouped.setdefault(item.carretera, []).append(item)
    return grouped


def _route_between(
    source: gpd.GeoDataFrame, cols: dict[str, str | None], carretera: str, branch: str, pk1: float, pk2: float
) -> tuple[LineString | MultiLineString, float] | None:
    road_col = cols.get("carretera")
    m0, m1, scale = m_values(source, cols)
    low, high = sorted((pk1, pk2))
    pieces: list[LineString] = []
    for index, row in source.iterrows():
        if str(row.get(road_col)) != carretera or _branch_value(row, cols, index) != branch:
            continue
        geometry = _valid_line(row.geometry)
        bounds = _row_pk_bounds(row, m0, m1, scale)
        if geometry is None or bounds is None or abs(bounds[1] - bounds[0]) < 1e-12:
            continue
        row_low, row_high = sorted(bounds)
        start, end = max(low, row_low), min(high, row_high)
        if end - start <= 1e-9:
            continue
        d0 = (start - bounds[0]) / (bounds[1] - bounds[0]) * geometry.length
        d1 = (end - bounds[0]) / (bounds[1] - bounds[0]) * geometry.length
        part = substring(geometry, d0, d1)
        if isinstance(part, LineString) and part.length > 0:
            pieces.append(part)
    if not pieces:
        return None
    combined = unary_union(pieces)
    merged = combined if isinstance(combined, LineString) else linemerge(combined)
    # A MultiLineString here means that the calibrated pieces do not form one
    # traversable branch.  Never turn a gap into a fictitious road distance.
    if not isinstance(merged, LineString):
        return None
    return merged, float(sum(piece.length for piece in pieces))


def medir(
    lineas: gpd.GeoDataFrame,
    cols: dict[str, str | None],
    p1: Point,
    p2: Point,
    tolerance_m: float,
    carretera: str | None = None,
) -> dict[str, Any]:
    source = _metric_source(lineas)
    first = agrupar_candidatos(punto_a_pk(source, cols, p1, tolerance_m))
    second = agrupar_candidatos(punto_a_pk(source, cols, p2, tolerance_m))
    common = sorted(set(first) & set(second))
    if carretera:
        common = [road for road in common if road == carretera]
    if not common:
        return {"estado": "incompatible", "carreteras": []}
    if len(common) > 1 and not carretera:
        return {"estado": "ambiguo", "carreteras": common}

    road = common[0]
    options: list[tuple[float, PuntoCalibrado, PuntoCalibrado, LineString | MultiLineString, float]] = []
    for left in first[road]:
        for right in second[road]:
            if left.branch != right.branch:
                continue
            route = _route_between(source, cols, road, left.branch, left.pk, right.pk)
            if route is None:
                continue
            geometry, length = route
            options.append((left.distancia_m + right.distancia_m, left, right, geometry, length))
    if not options:
        return {"estado": "incompatible", "carreteras": []}
    _cost, left, right, geometry, length = min(options, key=lambda item: item[0])
    result_gdf = gpd.GeoDataFrame(geometry=[geometry], crs=source.crs).to_crs(4326)
    snapped = gpd.GeoSeries([left.snapped, right.snapped], crs=source.crs).to_crs(4326)
    return {
        "estado": "ok",
        "carretera": road,
        "pk1": left.pk,
        "pk2": right.pk,
        "distancia_geometria_m": length,
        "diferencia_pk_m": abs(right.pk - left.pk) * 1000.0,
        "p1": _point_json(snapped.iloc[0]),
        "p2": _point_json(snapped.iloc[1]),
        "geometry": result_gdf.geometry.iloc[0].__geo_interface__,
    }


def _point_json(point: Point) -> dict[str, float]:
    return {"lon": float(point.x), "lat": float(point.y)}


def punto_wgs84(point: Point, source_crs: Any) -> dict[str, float]:
    converted = gpd.GeoSeries([point], crs=source_crs).to_crs(4326).iloc[0]
    return _point_json(converted)


def vias_geojson(lineas: gpd.GeoDataFrame, cols: dict[str, str | None]) -> dict[str, Any]:
    if lineas.empty:
        return {"type": "FeatureCollection", "features": []}
    source = lineas.to_crs(4326)
    road_col, type_col = cols.get("carretera"), cols.get("tipo_via")
    features = []
    for _, row in source.iterrows():
        geometry = row.geometry
        if geometry is None or geometry.is_empty:
            continue
        road = str(row.get(road_col) or "") if road_col else ""
        road_type = str(row.get(type_col) or "") if type_col else ""
        features.append({
            "type": "Feature",
            "geometry": geometry.__geo_interface__,
            "properties": {"carretera": road, "tipo_via": road_type, "autovia": is_autovia(road, road_type)},
        })
    return {"type": "FeatureCollection", "features": features}
