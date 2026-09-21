from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, Point

from .utils import as_float, format_pk
from .referenciacion_lineal import (
    METHOD_GEOMETRY_M,
    component_coordinates,
    extract_between_m_with_calibration,
    m_range,
)


class TramoError(ValueError):
    pass


@dataclass
class TramoExtraido:
    carretera: str
    sentido: str
    pk_inicio_usuario: float
    pk_fin_usuario: float
    pk_inicio_recorrido: float
    pk_fin_recorrido: float
    pk_min: float
    pk_max: float
    longitud_m: float
    geometry: LineString | MultiLineString
    crs: Any
    advertencias: list[str]
    metadatos: dict[str, Any]
    # Deliberately internal: it can contain a vertex per source coordinate and
    # must not be copied to JSON metadata or generated output manifests.
    calibracion_distancia_m: list[tuple[float, float]] = field(default_factory=list)


def _field(cols: dict[str, str | None], name: str) -> str:
    value = cols.get(name)
    if not value:
        raise TramoError(f"No se detecto el campo requerido: {name}")
    return value


def m_values(gdf: gpd.GeoDataFrame, cols: dict[str, str | None]) -> tuple[str, str, float]:
    """Return the calibrated fields and their conversion to metres.

    This small public helper is shared by the interactive viewer so both entry
    points apply exactly the same field-name and fallback rules.
    """
    m0 = _field(cols, "m_inicio")
    m1 = _field(cols, "m_fin")
    names = [m0.lower(), m1.lower()]
    metric_names = {
        "m_from",
        "m_to",
        "m_inicio",
        "m_fin",
        "metro_inicio",
        "metro_fin",
        "metres_from",
        "metres_to",
    }
    if any(name in metric_names or name.startswith("m_") or name.endswith("_m") for name in names):
        return m0, m1, 1.0
    if any(name.startswith("pk_") or name.startswith("pk") or "kilometr" in name for name in names):
        return m0, m1, 1000.0
    values = []
    for col in [m0, m1]:
        values.extend([as_float(v) for v in gdf[col].head(1000).tolist()])
    values = [v for v in values if v is not None]
    scale = 1000.0 if values and max(abs(v) for v in values) < 2000 else 1.0
    return m0, m1, scale


# Backwards-compatible private name used by the existing extraction code/tests.
_m_values = m_values


def _normaliza_sentido(sentido: str) -> str:
    text = (sentido or "creciente").strip().lower()
    if text in {"decreciente", "descendente", "2", "down"}:
        return "decreciente"
    return "creciente"


def _filter_source_direction(gdf: gpd.GeoDataFrame, cols: dict[str, str | None], sentido: str) -> tuple[gpd.GeoDataFrame, list[str]]:
    notes: list[str] = []
    sentido_col = cols.get("sentido")
    if not sentido_col or sentido_col not in gdf.columns:
        return gdf, notes
    preferred = "1" if sentido == "creciente" else "2"
    series = gdf[sentido_col].astype(str).str.lower()
    mask = series.str.endswith(f"_s_{preferred}") | (series == preferred) | (series == f"{preferred}.0")
    selected = gdf.loc[mask].copy()
    if len(selected) == 0:
        notes.append(f"No se encontro sentido geometrico {preferred}; se usan todas las geometria de la carretera.")
        return gdf, notes
    return selected, notes


def rango_disponible(lineas: gpd.GeoDataFrame, cols: dict[str, str | None]) -> tuple[float, float]:
    m0, m1, scale = _m_values(lineas, cols)
    starts = lineas[m0].map(as_float).dropna().astype(float) * scale
    ends = lineas[m1].map(as_float).dropna().astype(float) * scale
    if starts.empty or ends.empty:
        raise TramoError("No hay campos M/PK validos para calcular el rango disponible.")
    low = min(starts.min(), ends.min()) / 1000.0
    high = max(starts.max(), ends.max()) / 1000.0
    return float(low), float(high)


def lineas_para_sentido(lineas: gpd.GeoDataFrame, cols: dict[str, str | None], sentido: str) -> tuple[gpd.GeoDataFrame, list[str]]:
    sentido_norm = _normaliza_sentido(sentido)
    source, notes = _filter_source_direction(lineas, cols, sentido_norm)
    if "ORIGINAL" in source.columns:
        preferred = source[source["ORIGINAL"].astype(str).str.upper().isin(["SI", "1", "TRUE"])]
        if len(preferred):
            source = preferred
    return source, notes


def rango_disponible_sentido(lineas: gpd.GeoDataFrame, cols: dict[str, str | None], sentido: str) -> tuple[float, float, list[str]]:
    source, notes = lineas_para_sentido(lineas, cols, sentido)
    low, high = rango_disponible(source, cols)
    return low, high, notes


def ajustar_pk_a_rango(pk: float, low: float, high: float) -> tuple[float, str | None]:
    value = float(pk)
    if value < low:
        return float(low), f"PK introducido {format_pk(value)} fuera de rango ({format_pk(low)} a {format_pk(high)}); se ajusta al PK real mas cercano {format_pk(low)}."
    if value > high:
        return float(high), f"PK introducido {format_pk(value)} fuera de rango ({format_pk(low)} a {format_pk(high)}); se ajusta al PK real mas cercano {format_pk(high)}."
    return value, None


def _line_endpoints(geometry: LineString | MultiLineString) -> tuple[Point, Point] | None:
    if geometry.is_empty:
        return None
    if isinstance(geometry, LineString):
        coords = list(geometry.coords)
        if not coords:
            return None
        return Point(coords[0]), Point(coords[-1])
    parts = list(geometry.geoms)
    if not parts:
        return None
    first_coords = list(parts[0].coords)
    last_coords = list(parts[-1].coords)
    if not first_coords or not last_coords:
        return None
    return Point(first_coords[0]), Point(last_coords[-1])


def _reverse_geometry(geometry: LineString | MultiLineString) -> LineString | MultiLineString:
    if isinstance(geometry, LineString):
        return LineString(list(geometry.coords)[::-1])
    return MultiLineString([LineString(list(part.coords)[::-1]) for part in list(geometry.geoms)[::-1]])


def _orient_to_pk_start(
    geometry: LineString | MultiLineString,
    pks: gpd.GeoDataFrame | None,
    pk_cols: dict[str, str | None] | None,
    pk_start: float,
    sentido: str,
) -> LineString | MultiLineString:
    endpoints = _line_endpoints(geometry)
    if not endpoints:
        return geometry
    start_pt, end_pt = endpoints
    if pks is not None and pk_cols:
        pk_col = pk_cols.get("pk")
        if pk_col and pk_col in pks.columns and len(pks):
            tmp = pks.copy()
            tmp["_pk_diff"] = (tmp[pk_col].astype(float) - float(pk_start)).abs()
            nearest = tmp.sort_values("_pk_diff").head(1)
            if len(nearest) and nearest.geometry.iloc[0] is not None:
                target = nearest.geometry.iloc[0]
                if end_pt.distance(target) < start_pt.distance(target):
                    return _reverse_geometry(geometry)
                return geometry
    if sentido == "decreciente":
        return _reverse_geometry(geometry)
    return geometry


def extraer_tramo(
    lineas: gpd.GeoDataFrame,
    cols: dict[str, str | None],
    carretera: str,
    pk_inicio: float,
    pk_fin: float,
    sentido: str,
    pks: gpd.GeoDataFrame | None = None,
    pk_cols: dict[str, str | None] | None = None,
) -> TramoExtraido:
    warnings: list[str] = []
    sentido_norm = _normaliza_sentido(sentido)
    if lineas.empty:
        raise TramoError(f"No hay geometria para la carretera {carretera}.")

    source, direction_notes = lineas_para_sentido(lineas, cols, sentido_norm)
    warnings.extend(direction_notes)

    available_min, available_max = rango_disponible(source, cols)
    user_start = float(pk_inicio)
    user_end = float(pk_fin)
    if sentido_norm == "creciente":
        route_start, route_end = min(user_start, user_end), max(user_start, user_end)
        if user_start > user_end:
            warnings.append("PK inicio > PK fin con sentido creciente; se ha normalizado el recorrido de menor a mayor PK.")
    else:
        route_start, route_end = max(user_start, user_end), min(user_start, user_end)
        if user_start < user_end:
            warnings.append("PK inicio < PK fin con sentido decreciente; se ha normalizado el recorrido de mayor a menor PK.")

    pk_low, pk_high = min(route_start, route_end), max(route_start, route_end)
    if pk_low < available_min or pk_high > available_max:
        raise TramoError(
            f"PK fuera de rango para {carretera}. Disponible: {format_pk(available_min)} a {format_pk(available_max)}."
        )

    start_m = pk_low * 1000.0
    end_m = pk_high * 1000.0
    m0, m1, scale = _m_values(source, cols)
    pieces: list[tuple[float, LineString, list[tuple[float, float]]]] = []
    methods: list[str] = []
    discontinuities = 0
    for _, row in source.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        row_start = as_float(row.get(m0))
        row_end = as_float(row.get(m1))
        if row_start is None or row_end is None:
            continue
        row_start_m = row_start * scale
        row_end_m = row_end * scale
        row_low, row_high = min(row_start_m, row_end_m), max(row_start_m, row_end_m)
        overlap_start = max(start_m, row_low)
        overlap_end = min(end_m, row_high)
        if overlap_end <= overlap_start:
            continue
        for _item, coords, component_method in component_coordinates(row, geom, row_start_m, row_end_m):
            component_range = m_range(coords)
            if component_range is None:
                continue
            component_low, component_high = component_range
            overlap_start = max(start_m, component_low)
            overlap_end = min(end_m, component_high)
            if overlap_end <= overlap_start:
                continue
            piece_start, piece_end = (overlap_end, overlap_start) if sentido_norm == "decreciente" else (overlap_start, overlap_end)
            part, calibration = extract_between_m_with_calibration(coords, piece_start, piece_end)
            if part is not None:
                pieces.append((overlap_start, part, calibration))
                methods.append(component_method)
    if not pieces:
        raise TramoError("No se pudo extraer geometria para el rango PK solicitado.")
    pieces.sort(key=lambda item: item[0], reverse=sentido_norm == "decreciente")
    # Keep the geometry in the same, explicit sequence as the calibration.
    # Union/linemerge can reorder or invert components and would desynchronise M.
    geometry = pieces[0][1] if len(pieces) == 1 else MultiLineString([piece for _, piece, _ in pieces])
    if isinstance(geometry, MultiLineString) and len(geometry.geoms) > 1:
        discontinuities = len(geometry.geoms) - 1
        warnings.append(f"El tramo tiene {len(geometry.geoms)} partes; posible discontinuidad geometrica.")
    if geometry.length <= 0:
        raise TramoError("La geometria extraida tiene longitud cero.")

    if any(method != METHOD_GEOMETRY_M for method in methods):
        warnings.append("Alguna geometría no expone M real; se usa el fallback explícito por límites de fila.")
    calibration: list[tuple[float, float]] = []
    distance = 0.0
    for _part_start, part, part_calibration in pieces:
        calibration.extend((distance + local_distance, measured) for local_distance, measured in part_calibration)
        distance += float(part.length)
    return TramoExtraido(
        carretera=carretera,
        sentido=sentido_norm,
        pk_inicio_usuario=user_start,
        pk_fin_usuario=user_end,
        pk_inicio_recorrido=route_start,
        pk_fin_recorrido=route_end,
        pk_min=pk_low,
        pk_max=pk_high,
        longitud_m=float(geometry.length),
        geometry=geometry,
        crs=source.crs,
        advertencias=warnings,
        metadatos={
            "pk_disponible_min": available_min,
            "pk_disponible_max": available_max,
            "partes": len(geometry.geoms) if isinstance(geometry, MultiLineString) else 1,
            "discontinuidades": discontinuities,
            "referenciacion_lineal": {"metodo": METHOD_GEOMETRY_M if methods and all(item == METHOD_GEOMETRY_M for item in methods) else "row_bounds_xy_fallback"},
        },
        calibracion_distancia_m=calibration,
    )
