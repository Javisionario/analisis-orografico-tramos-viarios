from __future__ import annotations

"""Small, side-effect-free helpers shared by the road-viewer PK endpoints."""

import csv
import math
import re
from io import StringIO
from pathlib import Path
from typing import Any, Iterable

import geopandas as gpd
from shapely.geometry import Point

from .io_datos import normalize_road_name


VALID_INTERVALS = {1, 5, 10, 25, 50}
_TEXT_LINE = re.compile(r"^\s*(?P<road>[^,;\s]+)\s*(?:[,;]|\s+)\s*(?P<pk>[-+]?\d+(?:[.,]\d+)?(?:\+\d{1,3})?)\s*$")


def format_pk(pk: float) -> str:
    metres = int(round(float(pk) * 1000))
    sign = "-" if metres < 0 else ""
    metres = abs(metres)
    return f"{sign}{metres // 1000}+{metres % 1000:03d}"


def parse_pk_value(value: str) -> float:
    text = str(value).strip().replace(",", ".")
    if "+" in text:
        km, metres = text.split("+", 1)
        if not km or not metres or not metres.isdigit() or len(metres) > 3:
            raise ValueError("PK no válido")
        return float(km) + int(metres) / 1000.0
    result = float(text)
    if not math.isfinite(result):
        raise ValueError("PK no válido")
    return result


def parse_pk_text(text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    points: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for line_number, raw in enumerate(str(text or "").splitlines(), 1):
        if not raw.strip():
            continue
        match = _TEXT_LINE.match(raw)
        if not match:
            errors.append({"linea": line_number, "texto": raw, "detalle": "Formato no reconocido."})
            continue
        try:
            points.append({"carretera": match.group("road").strip(), "pk": parse_pk_value(match.group("pk")), "indice": len(points)})
        except ValueError:
            errors.append({"linea": line_number, "texto": raw, "detalle": "PK no válido."})
    return points, errors


def pk_km(value: Any, column: str | None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    # VALORKM is already km. VALORM-like fields are metres.
    return number / 1000.0 if str(column or "").lower() in {"valorm", "m", "metros"} else number


def tangent_rotation(point: Point, lines: gpd.GeoDataFrame) -> float | None:
    """CSS clockwise angle for an undirected, road-parallel tick line."""
    candidates = [geometry for geometry in lines.geometry if geometry is not None and not geometry.is_empty and geometry.length]
    if not candidates:
        return None
    line = min(candidates, key=lambda geometry: geometry.distance(point))
    position = line.project(point)
    offset = min(20.0, max(1.0, line.length / 20.0))
    first = line.interpolate(max(0.0, position - offset))
    last = line.interpolate(min(line.length, position + offset))
    if first.equals(last):
        return None
    return round((-math.degrees(math.atan2(last.y - first.y, last.x - first.x))) % 180.0, 2)


def pk_bbox_items(pks: gpd.GeoDataFrame, cols: dict[str, str | None], lines: gpd.GeoDataFrame, roads: Iterable[str], interval: int) -> list[dict[str, Any]]:
    road_col, pk_col = cols.get("carretera"), cols.get("pk")
    if not road_col or not pk_col:
        raise ValueError("No se detectaron los campos de carretera y PK.")
    wanted = {normalize_road_name(value) for value in roads if normalize_road_name(value)}
    if not wanted:
        return []
    result: list[dict[str, Any]] = []
    source = pks.to_crs(4326) if pks.crs and str(pks.crs) != "EPSG:4326" else pks
    for index, row in source.iterrows():
        road = str(row.get(road_col) or "").strip()
        pk = pk_km(row.get(pk_col), pk_col)
        if normalize_road_name(road) not in wanted or pk is None or int(round(pk)) % interval:
            continue
        geometry = row.geometry
        if geometry is None or geometry.is_empty:
            continue
        raw_rotation = row.get(cols.get("rotacion")) if cols.get("rotacion") else None
        try:
            raw_rotation = float(raw_rotation)
            if not math.isfinite(raw_rotation):
                raw_rotation = None
        except (TypeError, ValueError):
            raw_rotation = None
        result.append({
            "carretera": road,
            "pk": round(pk, 3),
            "pk_formateado": format_pk(pk),
            "lon": round(float(geometry.x), 7),
            "lat": round(float(geometry.y), 7),
            "rotacion": raw_rotation,
            "rotacion_tangente": tangent_rotation(pks.loc[index].geometry, lines),
        })
    return result


def export_rows(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in points:
        road = str(item.get("carretera") or "").strip()
        try:
            pk, lon, lat = float(item.get("pk")), float(item.get("longitud")), float(item.get("latitud"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Cada punto debe incluir carretera, PK, longitud y latitud válidos.") from exc
        if not road or not all(math.isfinite(value) for value in (pk, lon, lat)) or not -180 <= lon <= 180 or not -90 <= lat <= 90:
            raise ValueError("Cada punto debe incluir carretera, PK, longitud y latitud válidos.")
        rows.append({"carretera": road, "pk": format_pk(pk), "pk_numerico": pk, "longitud": lon, "latitud": lat})
    return rows


def csv_text(rows: list[dict[str, Any]]) -> str:
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=["carretera", "pk", "pk_numerico", "longitud", "latitud"])
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def write_gpkg(rows: list[dict[str, Any]], target: Path) -> None:
    data = gpd.GeoDataFrame(rows, geometry=[Point(item["longitud"], item["latitud"]) for item in rows], crs="EPSG:4326")
    data.to_file(target, layer="pks", driver="GPKG")
