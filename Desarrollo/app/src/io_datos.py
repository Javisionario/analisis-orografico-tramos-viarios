from __future__ import annotations

import warnings
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any
import re
import unicodedata

import geopandas as gpd
import pyogrio

from .referenciacion_lineal import measured_parts_from_gpkg

from .utils import choose_column, resolve_data_path


_ROAD_OPTIONS_CACHE: dict[tuple[str, str, float], list[dict[str, Any]]] = {}
_ADMIN_CACHE: dict[tuple[str, int, str, str], tuple[gpd.GeoDataFrame | None, gpd.GeoDataFrame | None, list[str]]] = {}


def _datos_config(config: dict[str, Any]) -> dict[str, Any]:
    return config.get("datos", {})


def _campos_config(config: dict[str, Any]) -> dict[str, list[str]]:
    return config.get("campos", {})


def viario_path(config: dict[str, Any]) -> Path:
    return resolve_data_path(_datos_config(config).get("viario_gpkg", ""))


def limites_path(config: dict[str, Any]) -> Path:
    return resolve_data_path(_datos_config(config).get("limites_gpkg", ""))


def line_layer(config: dict[str, Any]) -> str:
    return str(_datos_config(config).get("capa_lineas", ""))


def pk_layer(config: dict[str, Any]) -> str:
    return str(_datos_config(config).get("capa_pks", ""))


def list_layers(path: Path) -> tuple[list[dict[str, str | None]], list[str]]:
    notes: list[str] = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        rows = pyogrio.list_layers(path).tolist()
    for item in caught:
        msg = str(item.message)
        if "Measured" in msg or "(M)" in msg:
            notes.append(msg)
    return [{"name": str(row[0]), "geometry_type": row[1]} for row in rows], notes


def _attach_measured_parts(path: Path, layer: str, gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Attach raw M coordinates keyed by GeoPackage fid when available."""
    if gdf.empty or not path.suffix.lower() == ".gpkg":
        return gdf
    try:
        fids = [int(index) for index in gdf.index]
        by_fid: dict[int, list[list[tuple[float, float, float]]]] = {}
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
            # SQLite commonly limits bound variables to 999. BBOX responses can
            # legitimately exceed that, so retain the FID association in chunks.
            for start in range(0, len(fids), 900):
                chunk = fids[start : start + 900]
                marks = ",".join("?" for _ in chunk)
                query = f'SELECT fid, geom FROM {_quote_identifier(layer)} WHERE fid IN ({marks})'
                for fid, blob in conn.execute(query, tuple(chunk)):
                    by_fid[int(fid)] = measured_parts_from_gpkg(blob)
        result = gdf.copy(); result["__m_parts"] = [by_fid.get(int(index), []) for index in result.index]
        return result
    except Exception as exc:
        gdf.attrs["m_parts_error"] = str(exc)
        return gdf


def _reconcile_m_notes(gdf: gpd.GeoDataFrame, notes: list[str]) -> list[str]:
    """Do not report pyogrio's M-loss warning after successful raw recovery."""
    measured_warning = any("Measured" in note or "(M)" in note for note in notes)
    if not measured_warning:
        # Points and polygons have no M by design. Their empty raw-coordinate
        # column must never become a road-calibration fallback warning.
        return notes
    if "__m_parts" not in gdf.columns:
        return notes
    result = [note for note in notes if "Measured" not in note and "(M)" not in note]
    missing = int(sum(not bool(parts) for parts in gdf["__m_parts"]))
    if missing:
        result.append(f"No se pudo recuperar M real en {missing} geometrías; se aplicará fallback explícito por fila.")
    return result


def read_layer(path: Path, layer: str, where: str | None = None, rows: int | None = None) -> tuple[gpd.GeoDataFrame, list[str]]:
    notes: list[str] = []
    kwargs: dict[str, Any] = {"layer": layer}
    if where:
        kwargs["where"] = where
    if rows:
        kwargs["max_features"] = rows
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        gdf = pyogrio.read_dataframe(path, fid_as_index=True, **kwargs)
    for item in caught:
        msg = str(item.message)
        if "Measured" in msg or "(M)" in msg:
            notes.append(msg)
    result = _attach_measured_parts(path, layer, gdf)
    return result, _reconcile_m_notes(result, notes)


def sql_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def normalize_road_name(value: Any) -> str:
    text = str(value or "").strip().upper()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[\s_\-]+", "", text)
    return text


def _quote_identifier(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def detect_columns(gdf: gpd.GeoDataFrame, config: dict[str, Any], pk: bool = False) -> dict[str, str | None]:
    campos = _campos_config(config)
    columns = [str(col) for col in gdf.columns]
    if pk:
        return {
            "carretera": choose_column(columns, campos.get("carretera_pks", [])),
            "sentido": choose_column(columns, campos.get("sentido_pks", [])),
            "pk": choose_column(columns, campos.get("pk_punto", [])),
            "label": choose_column(columns, campos.get("etiqueta_pk", [])),
            "z": choose_column(columns, campos.get("cota_pk", [])),
            "rotacion": choose_column(columns, campos.get("rotacion_pks", [])),
        }
    return {
        "carretera": choose_column(columns, campos.get("carretera_lineas", [])),
        "sentido": choose_column(columns, campos.get("sentido_lineas", [])),
        "m_inicio": choose_column(columns, campos.get("m_inicio", [])),
        "m_fin": choose_column(columns, campos.get("m_fin", [])),
        "tipo_via": choose_column(columns, campos.get("tipo_via", [])),
    }


def load_lineas(config: dict[str, Any], carretera: str | None = None) -> tuple[gpd.GeoDataFrame, dict[str, str | None], list[str]]:
    path = viario_path(config)
    layer = line_layer(config)
    notes: list[str] = []
    where = None
    if carretera:
        probe, probe_notes = read_layer(path, layer, rows=1)
        notes.extend(probe_notes)
        cols = detect_columns(probe, config, pk=False)
        road_col = cols.get("carretera")
        if road_col:
            where = f"{_quote_identifier(road_col)} = {sql_quote(carretera)}"
    gdf, layer_notes = read_layer(path, layer, where=where)
    notes.extend(layer_notes)
    return gdf, detect_columns(gdf, config, pk=False), notes


def load_pks(config: dict[str, Any], carretera: str | None = None) -> tuple[gpd.GeoDataFrame, dict[str, str | None], list[str]]:
    path = viario_path(config)
    layer = pk_layer(config)
    notes: list[str] = []
    where = None
    if carretera:
        probe, probe_notes = read_layer(path, layer, rows=1)
        notes.extend(probe_notes)
        cols = detect_columns(probe, config, pk=True)
        road_col = cols.get("carretera")
        if road_col:
            where = f"{_quote_identifier(road_col)} = {sql_quote(carretera)}"
    gdf, layer_notes = read_layer(path, layer, where=where)
    notes.extend(layer_notes)
    return gdf, detect_columns(gdf, config, pk=True), notes


def _list_road_options_uncached(config: dict[str, Any]) -> list[dict[str, Any]]:
    path = viario_path(config)
    layer = line_layer(config)
    probe, _notes = read_layer(path, layer, rows=1)
    cols = detect_columns(probe, config, pk=False)
    road_col = cols.get("carretera")
    m0 = cols.get("m_inicio")
    m1 = cols.get("m_fin")
    if not road_col:
        return []
    if m0 and m1:
        try:
            sql = (
                f"SELECT {_quote_identifier(road_col)} AS road, "
                f"MIN({_quote_identifier(m0)}) AS min0, MAX({_quote_identifier(m0)}) AS max0, "
                f"MIN({_quote_identifier(m1)}) AS min1, MAX({_quote_identifier(m1)}) AS max1, "
                f"COUNT(*) AS n FROM {_quote_identifier(layer)} "
                f"WHERE {_quote_identifier(road_col)} IS NOT NULL "
                f"GROUP BY {_quote_identifier(road_col)}"
            )
            rows = []
            with sqlite3.connect(path) as conn:
                for road, min0, max0, min1, max1, n in conn.execute(sql):
                    values = [float(v) for v in [min0, max0, min1, max1] if v is not None]
                    item = {"carretera": str(road), "normalizado": normalize_road_name(road), "segmentos": int(n)}
                    if values:
                        scale = 1000.0 if str(m0).lower().startswith("m_") or str(m1).lower().startswith("m_") else 1.0
                        item["pk_min"] = float(min(values) / scale)
                        item["pk_max"] = float(max(values) / scale)
                    rows.append(item)
            rows.sort(key=lambda x: x["normalizado"])
            return rows
        except Exception:
            pass
    columns = [col for col in [road_col, m0, m1] if col]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            gdf = pyogrio.read_dataframe(path, layer=layer, columns=columns, read_geometry=False)
    except Exception:
        gdf, cols, _notes = load_lineas(config)
    rows = []
    for road, group in gdf.groupby(road_col, dropna=True):
        item = {"carretera": str(road), "normalizado": normalize_road_name(road), "segmentos": int(len(group))}
        if m0 and m1:
            starts = group[m0].astype(float)
            ends = group[m1].astype(float)
            scale = 1000.0 if str(m0).lower().startswith("m_") or str(m1).lower().startswith("m_") else 1.0
            item["pk_min"] = float(min(starts.min(), ends.min()) / scale)
            item["pk_max"] = float(max(starts.max(), ends.max()) / scale)
        rows.append(item)
    rows.sort(key=lambda x: x["carretera"])
    return rows


def list_road_options(config: dict[str, Any], limit: int | None = None, q: str | None = None) -> list[dict[str, Any]]:
    path = viario_path(config)
    layer = line_layer(config)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    key = (str(path), layer, mtime)
    rows = _ROAD_OPTIONS_CACHE.get(key)
    if rows is None:
        rows = _list_road_options_uncached(config)
        _ROAD_OPTIONS_CACHE.clear()
        _ROAD_OPTIONS_CACHE[key] = rows
    query = normalize_road_name(q)
    if query:
        rows = [item for item in rows if query in str(item.get("normalizado") or normalize_road_name(item["carretera"]))]
    if limit and limit > 0:
        return rows[:limit]
    return rows


def resolve_road_name(config: dict[str, Any], value: str) -> str | None:
    target = normalize_road_name(value)
    if not target:
        return None
    for item in list_road_options(config, limit=None):
        if str(item.get("normalizado") or normalize_road_name(item["carretera"])) == target:
            return str(item["carretera"])
    return None


def read_layer_bbox(path: Path, layer: str, bbox: tuple[float, float, float, float]) -> tuple[gpd.GeoDataFrame, list[str]]:
    notes: list[str] = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        gdf = pyogrio.read_dataframe(path, layer=layer, bbox=bbox, fid_as_index=True)
    for item in caught:
        msg = str(item.message)
        if "Measured" in msg or "(M)" in msg:
            notes.append(msg)
    result = _attach_measured_parts(path, layer, gdf)
    return result, _reconcile_m_notes(result, notes)


def load_lineas_bbox(config: dict[str, Any], bbox: tuple[float, float, float, float]) -> tuple[gpd.GeoDataFrame, dict[str, str | None], list[str]]:
    path = viario_path(config)
    layer = line_layer(config)
    gdf, notes = read_layer_bbox(path, layer, bbox=bbox)
    return gdf, detect_columns(gdf, config, pk=False), notes


def load_pks_bbox(config: dict[str, Any], bbox: tuple[float, float, float, float]) -> tuple[gpd.GeoDataFrame, dict[str, str | None], list[str]]:
    """Read only PK points intersecting a source-CRS bounding box."""
    path = viario_path(config)
    layer = pk_layer(config)
    gdf, notes = read_layer_bbox(path, layer, bbox=bbox)
    return gdf, detect_columns(gdf, config, pk=True), notes


def _read_layer_bbox_roads(path: Path, layer: str, bbox: tuple[float, float, float, float], road_column: str, roads: list[str]) -> tuple[gpd.GeoDataFrame, list[str]]:
    """Read a spatially and attribute-filtered subset without materialising a national layer."""
    if not roads:
        return gpd.GeoDataFrame(geometry=[], crs=None), []
    where = f"{_quote_identifier(road_column)} IN ({', '.join(sql_quote(road) for road in roads)})"
    notes: list[str] = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        gdf = pyogrio.read_dataframe(path, layer=layer, bbox=bbox, where=where, fid_as_index=True)
    notes.extend(str(item.message) for item in caught if "Measured" in str(item.message) or "(M)" in str(item.message))
    result = _attach_measured_parts(path, layer, gdf)
    return result, _reconcile_m_notes(result, notes)


def load_lineas_bbox_roads(config: dict[str, Any], bbox: tuple[float, float, float, float], roads: list[str]) -> tuple[gpd.GeoDataFrame, dict[str, str | None], list[str]]:
    path, layer = viario_path(config), line_layer(config)
    probe, notes = read_layer(path, layer, rows=1)
    cols = detect_columns(probe, config, pk=False)
    road_column = cols.get("carretera")
    if not road_column:
        return gpd.GeoDataFrame(geometry=[], crs=probe.crs), cols, notes + ["No se detectó el campo de carretera."]
    gdf, read_notes = _read_layer_bbox_roads(path, layer, bbox, road_column, roads)
    return gdf, detect_columns(gdf, config, pk=False), notes + read_notes


def load_pks_bbox_roads(config: dict[str, Any], bbox: tuple[float, float, float, float], roads: list[str]) -> tuple[gpd.GeoDataFrame, dict[str, str | None], list[str]]:
    path, layer = viario_path(config), pk_layer(config)
    probe, notes = read_layer(path, layer, rows=1)
    cols = detect_columns(probe, config, pk=True)
    road_column = cols.get("carretera")
    if not road_column:
        return gpd.GeoDataFrame(geometry=[], crs=probe.crs), cols, notes + ["No se detectó el campo de carretera."]
    gdf, read_notes = _read_layer_bbox_roads(path, layer, bbox, road_column, roads)
    return gdf, detect_columns(gdf, config, pk=True), notes + read_notes


def load_admin(config: dict[str, Any]) -> tuple[gpd.GeoDataFrame | None, gpd.GeoDataFrame | None, list[str]]:
    path = limites_path(config)
    notes: list[str] = []
    if not path.exists():
        return None, None, [f"No existe el GPKG de limites: {path}"]
    ccaa_layer = str(_datos_config(config).get("capa_ccaa", "CCAA"))
    provincias_layer = str(_datos_config(config).get("capa_provincias", "Provincias"))
    try:
        cache_key = (str(path.resolve()), path.stat().st_mtime_ns, ccaa_layer, provincias_layer)
    except OSError:
        cache_key = (str(path), 0, ccaa_layer, provincias_layer)
    cached = _ADMIN_CACHE.get(cache_key)
    if cached is not None:
        ccaa, provincias, cached_notes = cached
        return (
            ccaa.copy() if ccaa is not None else None,
            provincias.copy() if provincias is not None else None,
            list(cached_notes),
        )
    ccaa = provincias = None
    try:
        ccaa, n = read_layer(path, ccaa_layer)
        notes.extend(n)
    except Exception as exc:
        notes.append(f"No se pudo leer CCAA: {exc}")
    try:
        provincias, n = read_layer(path, provincias_layer)
        notes.extend(n)
    except Exception as exc:
        notes.append(f"No se pudo leer Provincias: {exc}")
    _ADMIN_CACHE.clear()
    _ADMIN_CACHE[cache_key] = (ccaa, provincias, list(notes))
    return ccaa.copy() if ccaa is not None else None, provincias.copy() if provincias is not None else None, notes


def diagnostico_capas(config: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {"advertencias": []}
    for key, path in [("viario", viario_path(config)), ("limites", limites_path(config))]:
        item: dict[str, Any] = {"path": str(path), "existe": path.exists(), "layers": []}
        if path.exists():
            try:
                layers, notes = list_layers(path)
                item["layers"] = layers
                # Layer discovery can only report GDAL's generic conversion
                # warning. The authoritative recovery check happens below when
                # the configured road layer is read by FID.
                result["advertencias"].extend(note for note in notes if "Measured" not in note and "(M)" not in note)
            except Exception as exc:
                item["error"] = str(exc)
        result[key] = item
    try:
        lineas, cols, notes = load_lineas(config)
        result["lineas"] = {
            "layer": line_layer(config),
            "crs": str(lineas.crs),
            "filas": int(len(lineas)),
            "columnas": list(map(str, lineas.columns)),
            "campos_detectados": cols,
            "geom_types": sorted({str(v) for v in lineas.geometry.geom_type.dropna().unique()}),
            "has_z_sample": bool(lineas.geometry.dropna().iloc[0].has_z) if len(lineas.geometry.dropna()) else False,
            "has_m_sample": bool("__m_parts" in lineas.columns and any(bool(parts) for parts in lineas["__m_parts"])),
        }
        result["advertencias"].extend(notes)
    except Exception as exc:
        result["lineas_error"] = str(exc)
    try:
        pks, cols, notes = load_pks(config)
        result["pks"] = {
            "layer": pk_layer(config),
            "crs": str(pks.crs),
            "filas": int(len(pks)),
            "columnas": list(map(str, pks.columns)),
            "campos_detectados": cols,
            "geom_types": sorted({str(v) for v in pks.geometry.geom_type.dropna().unique()}),
        }
        result["advertencias"].extend(notes)
    except Exception as exc:
        result["pks_error"] = str(exc)
    if result.get("lineas", {}).get("has_m_sample") is False:
        result["advertencias"].append("No se pudo recuperar M real de la capa viaria; se aplicará el fallback explícito por límites de fila.")
    return result
