from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import os
from pathlib import Path
import tempfile
from threading import Lock
from time import perf_counter
from typing import Any
from uuid import uuid4

import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from src import APP_VERSION
from src.exportacion import generar_outputs
from src.credenciales import eliminar_api_key_carto, guardar_api_key_carto, obtener_api_key_carto
from src.io_datos import diagnostico_capas, line_layer, list_road_options, load_lineas, load_lineas_bbox, load_lineas_bbox_roads, load_pks_bbox_roads, resolve_road_name, viario_path
from src.tramo import ajustar_pk_a_rango, rango_disponible_sentido
from src.utils import load_config, resolve_tool_path
from src.visor_red import VisorRedError, agrupar_candidatos, bbox_wgs84_a_crs, localizar_pk, medir, punto_a_pk, punto_wgs84, vias_geojson
from src.visor_pks import VALID_INTERVALS, csv_text, export_rows, pk_bbox_items, write_gpkg, write_kmz
from src.subtramos import analizar_subtramos

import geopandas as gpd
import pyogrio
from pyproj import Transformer
from shapely.geometry import Point


ROOT = Path(__file__).resolve().parent
app = FastAPI(title="Herramienta tramos y pendientes", version=APP_VERSION)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")
# El compositor mantiene diagnósticos por generación; serializar jobs evita cruzarlos.
EXECUTOR = ThreadPoolExecutor(max_workers=1)
JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = Lock()
_VISOR_BOUNDS_CACHE: dict[tuple[str, str, int], tuple[float, float, float, float]] = {}

PROGRESS_PHASES = [
    "Preparando el tramo de estudio.",
    "Leyendo carretera y PKs.",
    "Cargando modelo digital del terreno.",
    "Muestreando cotas sobre la via.",
    "Calculando pendientes.",
    "Generando perfil longitudinal.",
    "Componiendo mapa de localizacion.",
    "Componiendo mapa de pendientes.",
    "Preparando archivos de descarga.",
    "Finalizando resultados.",
]


class TramoRequest(BaseModel):
    carretera: str
    pk_inicio: float
    pk_fin: float
    sentido: str = "creciente"


class GenerarRequest(BaseModel):
    # Los campos legacy se mantienen opcionales para aceptar un payload que use
    # exclusivamente ``tramos``. Las peticiones antiguas siguen enviándolos.
    carretera: str | None = None
    pk_inicio: float | None = None
    pk_fin: float | None = None
    sentido: str = "creciente"
    tramos: list[TramoRequest] | None = None
    agrupar_como_subtramos: bool = False
    pintar_pks: bool = True
    pk_modo: str = "automatico"
    pk_simbolo_cada: int | None = None
    pk_etiqueta_cada: int | None = None
    vias_fondo_modo: str = "todas"
    mapa_base: str = "ign_gris"
    carto_api_key: str | None = None
    recordar_carto_api_key: bool = False
    generar_mapa_localizacion: bool = True
    generar_mapa_pendientes: bool = True
    generar_perfil: bool = True
    generar_datos_auxiliares: bool = False
    generar_todo: bool = False
    resolucion_mdt: str = "5"
    intervalo_muestreo_m: float | None = None
    longitud_intervalo_pendiente_m: float | None = None
    suavizado: float | None = None
    suavizado_modo: str | None = None
    sg_window_puntos: int | None = None
    sg_polyorder: int | None = None
    sg_polyorder_slider_visual: int | None = None
    suavizado_elevaciones: float | None = None
    suavizado_elevaciones_modo: str | None = None
    sg_elevaciones_window_puntos: int | None = None
    sg_elevaciones_polyorder: int | None = None
    sg_elevaciones_polyorder_slider_visual: int | None = None
    suavizado_pendientes: float = 4.0
    suavizado_pendientes_modo: str = "simple"
    sg_pendientes_window_puntos: int | None = None
    sg_pendientes_polyorder: int | None = None
    sg_pendientes_polyorder_slider_visual: int | None = None
    umbral_pendiente_anomala_pct: float = 20.0
    modo_eje_y: str = "cero"
    mostrar_linea_muestreada_elevaciones: bool = False
    mostrar_anotaciones_curvas_nivel: bool = True
    alpha_elev_localizacion: float = 0.34
    alpha_elev_pendientes: float = 0.46


class IdentificarVisorRequest(BaseModel):
    lon: float
    lat: float
    tolerance_m: float


class PuntoVisorRequest(BaseModel):
    lon: float
    lat: float


class MedirVisorRequest(BaseModel):
    p1: PuntoVisorRequest
    p2: PuntoVisorRequest
    tolerance_m: float
    carretera: str | None = None


class LocalizarPuntoPkRequest(BaseModel):
    carretera: str
    pk: float


class LocalizarPksRequest(BaseModel):
    puntos: list[LocalizarPuntoPkRequest]


class ExportarPuntoPkRequest(BaseModel):
    carretera: str
    pk: float
    longitud: float
    latitud: float


class ExportarPksRequest(BaseModel):
    puntos: list[ExportarPuntoPkRequest]
    formato: str


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html", {"version": f"v{APP_VERSION}"})


@app.get("/api/diagnostico")
def diagnostico() -> dict[str, Any]:
    config = load_config()
    return diagnostico_capas(config)


@app.get("/api/carreteras")
def carreteras(q: str | None = Query(default=None), limit: int = Query(default=0, ge=0, le=100000)) -> dict[str, Any]:
    config = load_config()
    start = perf_counter()
    total = len(list_road_options(config, limit=None))
    matches = list_road_options(config, limit=None, q=q)
    items = matches[:limit] if limit and limit > 0 else matches
    return {
        "items": items,
        "q": q or "",
        "count": len(items),
        "total": total,
        "coincidencias": len(matches),
        "limit": limit,
        "elapsed_ms": round((perf_counter() - start) * 1000, 1),
    }


@app.get("/api/rango-carretera")
def rango_carretera(
    carretera: str = Query(...),
    sentido: str = Query(default="creciente"),
    pk_inicio: float | None = Query(default=None),
    pk_fin: float | None = Query(default=None),
) -> dict[str, Any]:
    config = load_config()
    resolved = resolve_road_name(config, carretera)
    if not resolved:
        raise HTTPException(status_code=404, detail=f"Carretera no encontrada: {carretera}")
    lineas, cols, notes = load_lineas(config, resolved)
    warnings = list(notes)
    sentido_norm = str(sentido or "creciente").strip().lower()
    if sentido_norm == "ambos":
        ranges: list[tuple[float, float]] = []
        for item in ("creciente", "decreciente"):
            try:
                item_low, item_high, item_notes = rango_disponible_sentido(lineas, cols, item)
                ranges.append((item_low, item_high))
                warnings.extend([f"{item}: {note}" for note in item_notes])
            except Exception as exc:
                warnings.append(f"No se pudo calcular rango para sentido {item}: {exc}")
        if not ranges:
            raise HTTPException(status_code=404, detail=f"No hay rango disponible para {carretera}.")
        low = min(item[0] for item in ranges)
        high = max(item[1] for item in ranges)
        range_notes = []
    else:
        low, high, range_notes = rango_disponible_sentido(lineas, cols, sentido_norm)
        warnings.extend(range_notes)
    ajustes = []
    for name, value in [("pk_inicio", pk_inicio), ("pk_fin", pk_fin)]:
        if value is None:
            continue
        adjusted, msg = ajustar_pk_a_rango(float(value), low, high)
        ajustes.append({"campo": name, "introducido": value, "ajustado": adjusted, "advertencia": msg})
    return {
        "carretera": resolved,
        "sentido": sentido_norm,
        "pk_min": low,
        "pk_max": high,
        "advertencias": warnings,
        "ajustes": ajustes,
    }


def _visor_bounds(config: dict[str, Any]) -> tuple[float, float, float, float]:
    path = viario_path(config)
    layer = line_layer(config)
    info = pyogrio.read_info(path, layer=layer)
    bounds = info.get("total_bounds")
    crs = info.get("crs")
    if not bounds or not crs:
        raise VisorRedError("La capa calibrada no declara extensión o CRS.")
    # The metadata extent is correct in the source CRS, but a single UTM
    # rectangle spanning peninsular and island roads produces fictitious WGS84
    # corners. Transform each feature envelope instead: this avoids loading
    # geometries while retaining a tight, conservative WGS84 extent.
    try:
        key = (str(path.resolve()), layer, path.stat().st_mtime_ns)
    except OSError:
        key = (str(path), layer, 0)
    cached = _VISOR_BOUNDS_CACHE.get(key)
    if cached is not None:
        return cached
    _, feature_bounds = pyogrio.read_bounds(path, layer=layer)
    if feature_bounds.shape[1] == 0:
        raise VisorRedError("La capa calibrada no contiene geometrías.")
    min_x, min_y, max_x, max_y = feature_bounds
    x_coordinates = (*min_x, *min_x, *max_x, *max_x)
    y_coordinates = (*min_y, *max_y, *min_y, *max_y)
    longitudes, latitudes = Transformer.from_crs(crs, 4326, always_xy=True).transform(x_coordinates, y_coordinates)
    result = (float(min(longitudes)), float(min(latitudes)), float(max(longitudes)), float(max(latitudes)))
    min_lon, min_lat, max_lon, max_lat = result
    if not (min_lon < max_lon and min_lat < max_lat and -180 <= min_lon <= 180 and -180 <= max_lon <= 180 and -90 <= min_lat <= 90 and -90 <= max_lat <= 90):
        raise VisorRedError("La extensión WGS84 de la capa no es válida.")
    _VISOR_BOUNDS_CACHE.clear()
    _VISOR_BOUNDS_CACHE[key] = result
    return result


def _bbox_en_capa(config: dict[str, Any], bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    info = pyogrio.read_info(viario_path(config), layer=line_layer(config))
    return bbox_wgs84_a_crs(bbox, info["crs"])


def _candidatos_visores(config: dict[str, Any], lon: float, lat: float, tolerance_m: float):
    tolerance = min(max(float(tolerance_m), 1.0), 500.0)
    source_crs = pyogrio.read_info(viario_path(config), layer=line_layer(config))["crs"]
    click = gpd.GeoSeries([Point(lon, lat)], crs=4326).to_crs(source_crs).iloc[0]
    bbox = (click.x - tolerance, click.y - tolerance, click.x + tolerance, click.y + tolerance)
    lineas, cols, _notes = load_lineas_bbox(config, bbox)
    return lineas, cols, click, tolerance


@app.get("/api/visor/bounds")
def visor_bounds() -> dict[str, list[list[float]]]:
    try:
        min_lon, min_lat, max_lon, max_lat = _visor_bounds(load_config())
        return {"bounds": [[min_lat, min_lon], [max_lat, max_lon]]}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@app.get("/api/visor/vias")
def visor_vias(bbox: str = Query(...)) -> dict[str, Any]:
    try:
        values = [float(value) for value in bbox.split(",")]
        if len(values) != 4 or values[0] >= values[2] or values[1] >= values[3]:
            raise ValueError("BBOX no válido.")
        config = load_config()
        lineas, cols, _notes = load_lineas_bbox(config, _bbox_en_capa(config, tuple(values)))
        return vias_geojson(lineas, cols)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


def _parse_viewer_bbox(value: str) -> tuple[float, float, float, float]:
    values = tuple(float(item) for item in value.split(","))
    if len(values) != 4 or values[0] >= values[2] or values[1] >= values[3]:
        raise ValueError("BBOX no válido.")
    west, south, east, north = values
    if not (-180 <= west <= 180 and -180 <= east <= 180 and -90 <= south <= 90 and -90 <= north <= 90):
        raise ValueError("BBOX fuera de WGS84.")
    return values


@app.get("/api/visor/pks")
def visor_pks(
    bbox: str = Query(...),
    carreteras: str = Query(...),
    intervalo: int = Query(...),
) -> dict[str, Any]:
    if intervalo not in VALID_INTERVALS:
        raise HTTPException(status_code=422, detail="Intervalo PK no válido.")
    roads = [item.strip() for item in carreteras.split(";") if item.strip()]
    if not roads:
        raise HTTPException(status_code=422, detail="Debe seleccionar al menos una carretera.")
    if len(roads) > 30:
        raise HTTPException(status_code=422, detail="Demasiadas carreteras seleccionadas.")
    try:
        config = load_config()
        roads = [resolve_road_name(config, road) for road in roads]
        roads = [road for road in roads if road]
        if not roads:
            raise ValueError("No se encontraron las carreteras seleccionadas.")
        source_bbox = _bbox_en_capa(config, _parse_viewer_bbox(bbox))
        pks, cols, _notes = load_pks_bbox_roads(config, source_bbox, roads)
        lineas, _line_cols, _line_notes = load_lineas_bbox_roads(config, source_bbox, roads)
        return {"items": pk_bbox_items(pks, cols, lineas, roads, intervalo), "intervalo": intervalo}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@app.get("/api/visor/vias-seleccionadas")
def visor_vias_seleccionadas(bbox: str = Query(...), carreteras: str = Query(...)) -> dict[str, Any]:
    roads = [item.strip() for item in carreteras.split(";") if item.strip()]
    if not roads or len(roads) > 30:
        raise HTTPException(status_code=422, detail="Seleccione entre una y 30 carreteras.")
    try:
        config = load_config()
        resolved = [resolve_road_name(config, road) for road in roads]
        resolved = [road for road in resolved if road]
        if not resolved:
            raise ValueError("No se encontraron las carreteras seleccionadas.")
        lineas, cols, _notes = load_lineas_bbox_roads(config, _bbox_en_capa(config, _parse_viewer_bbox(bbox)), resolved)
        return vias_geojson(lineas, cols)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None


@app.get("/api/visor/localizar-pk")
def visor_localizar_pk(carretera: str = Query(...), pk: float = Query(...)) -> dict[str, Any]:
    config = load_config()
    resolved = resolve_road_name(config, carretera)
    if not resolved:
        raise HTTPException(status_code=404, detail="Carretera no encontrada.")
    try:
        lineas, cols, _notes = load_lineas(config, resolved)
        result = localizar_pk(lineas, cols, resolved, pk)
        return {"carretera": result.carretera, "pk": result.pk, "punto": punto_wgs84(result.snapped, result.crs)}
    except VisorRedError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


@app.post("/api/visor/localizar-pks")
def visor_localizar_pks(payload: LocalizarPksRequest) -> dict[str, Any]:
    if not payload.puntos:
        raise HTTPException(status_code=422, detail="Debe indicar al menos un PK.")
    if len(payload.puntos) > 250:
        raise HTTPException(status_code=422, detail="El lote de PKs supera el máximo de 250 puntos.")
    config = load_config()
    grouped: dict[str, list[tuple[int, float]]] = {}
    errors: dict[int, str] = {}
    for index, point in enumerate(payload.puntos):
        if not -1e-9 <= point.pk <= 2000:
            errors[index] = "PK fuera de rango."
            continue
        road = resolve_road_name(config, point.carretera)
        if not road:
            errors[index] = "Carretera no encontrada."
            continue
        grouped.setdefault(road, []).append((index, point.pk))
    results: list[dict[str, Any]] = [{"indice": index, "error": errors[index]} if index in errors else {"indice": index} for index in range(len(payload.puntos))]
    for road, requests in grouped.items():
        try:
            lineas, cols, _notes = load_lineas(config, road)  # exactly once per resolved road
            for index, pk in requests:
                try:
                    item = localizar_pk(lineas, cols, road, pk)
                    results[index] = {"indice": index, "carretera": item.carretera, "pk": item.pk, "punto": punto_wgs84(item.snapped, item.crs)}
                except VisorRedError as exc:
                    results[index] = {"indice": index, "error": str(exc)}
        except Exception as exc:
            for index, _pk in requests:
                results[index] = {"indice": index, "error": str(exc)}
    return {"resultados": results}


def _remove_tempfile(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


@app.post("/api/visor/exportar-pks")
def visor_exportar_pks(payload: ExportarPksRequest, background_tasks: BackgroundTasks):
    formato = str(payload.formato or "").lower()
    if formato not in {"csv", "gpkg", "kmz"}:
        raise HTTPException(status_code=422, detail="Formato de exportación no válido.")
    try:
        rows = export_rows([item.model_dump() for item in payload.puntos])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    if not rows:
        raise HTTPException(status_code=422, detail="Debe seleccionar al menos un punto.")
    if formato == "csv":
        return PlainTextResponse(csv_text(rows), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="pks.csv"'})
    # Keep short-lived exports inside the application workspace: desktop sandbox
    # profiles can deny GDAL access to the system temporary directory.
    suffix = ".kmz" if formato == "kmz" else ".gpkg"
    handle = tempfile.NamedTemporaryFile(prefix="visor_pks_", suffix=suffix, dir=ROOT, delete=False)
    handle.close()
    try:
        (write_kmz if formato == "kmz" else write_gpkg)(rows, Path(handle.name))
    except Exception as exc:
        _remove_tempfile(handle.name)
        raise HTTPException(status_code=503, detail=f"No se pudo generar GPKG: {exc}") from None
    background_tasks.add_task(_remove_tempfile, handle.name)
    return FileResponse(handle.name, media_type="application/vnd.google-earth.kmz" if formato == "kmz" else "application/geopackage+sqlite3", filename=f"pks.{formato}", background=background_tasks)


@app.post("/api/visor/identificar")
def visor_identificar(payload: IdentificarVisorRequest) -> dict[str, Any]:
    try:
        config = load_config()
        lineas, cols, click, tolerance = _candidatos_visores(config, payload.lon, payload.lat, payload.tolerance_m)
        grouped = agrupar_candidatos(punto_a_pk(lineas, cols, click, tolerance))
        if not grouped:
            raise HTTPException(status_code=404, detail="No se encontró una vía calibrada próxima.")
        options = []
        for road in sorted(grouped):
            item = min(grouped[road], key=lambda value: value.distancia_m)
            options.append({"carretera": road, "pk": item.pk, "punto": punto_wgs84(item.snapped, item.crs)})
        if len(options) > 1:
            distances = sorted(min(item.distancia_m for item in grouped[road]) for road in grouped)
            if distances[1] - distances[0] > max(1.0, tolerance * 0.15):
                nearest = min(grouped, key=lambda road: min(item.distancia_m for item in grouped[road]))
                options = [item for item in options if item["carretera"] == nearest]
        return {"estado": "ok" if len(options) == 1 else "ambiguo", "opciones": options}
    except HTTPException:
        raise
    except VisorRedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.post("/api/visor/medir")
def visor_medir(payload: MedirVisorRequest) -> dict[str, Any]:
    try:
        config = load_config()
        tolerance = min(max(float(payload.tolerance_m), 1.0), 500.0)
        source_crs = pyogrio.read_info(viario_path(config), layer=line_layer(config))["crs"]
        clicks = gpd.GeoSeries([Point(payload.p1.lon, payload.p1.lat), Point(payload.p2.lon, payload.p2.lat)], crs=4326).to_crs(source_crs)
        nearby = []
        cols: dict[str, str | None] | None = None
        for click in clicks:
            x, y = click.x, click.y
            lineas, item_cols, _notes = load_lineas_bbox(config, (x - tolerance, y - tolerance, x + tolerance, y + tolerance))
            nearby.append((lineas, item_cols, click))
            cols = item_cols
        if cols is None:
            return {"estado": "incompatible", "carreteras": []}
        first = agrupar_candidatos(punto_a_pk(nearby[0][0], cols, nearby[0][2], tolerance))
        second = agrupar_candidatos(punto_a_pk(nearby[1][0], cols, nearby[1][2], tolerance))
        common = sorted(set(first) & set(second))
        if payload.carretera:
            common = [road for road in common if road == payload.carretera]
        if not common:
            return {"estado": "incompatible", "carreteras": []}
        if len(common) > 1 and not payload.carretera:
            return {"estado": "ambiguo", "carreteras": common}
        road = common[0]
        full_road, full_cols, _notes = load_lineas(config, road)
        return medir(full_road, full_cols, clicks.iloc[0], clicks.iloc[1], tolerance, road)
    except VisorRedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


@app.post("/generar")
def generar(payload: GenerarRequest) -> JSONResponse:
    if payload.mapa_base not in {"ign_gris", "carto_positron"}:
        raise HTTPException(status_code=422, detail="Mapa base no valido.")
    tramos = payload.tramos or []
    if payload.agrupar_como_subtramos:
        analysis = analizar_subtramos([item.model_dump() for item in tramos])
        if not analysis["valido"]:
            raise HTTPException(status_code=422, detail=analysis["motivo"])
    if len(tramos) > 1 and (payload.generar_mapa_pendientes or payload.generar_todo):
        raise HTTPException(
            status_code=422,
            detail="No se pueden generar mapas de pendientes cuando se analizan varios tramos.",
        )
    if not tramos and (not payload.carretera or payload.pk_inicio is None or payload.pk_fin is None):
        raise HTTPException(status_code=422, detail="Debe indicar carretera, PK inicio y PK fin.")
    api_key_introducida = str(payload.carto_api_key or "").strip()
    if api_key_introducida and payload.recordar_carto_api_key:
        guardar_api_key_carto(api_key_introducida)
    api_key_efectiva = api_key_introducida or obtener_api_key_carto()
    needs_maps = payload.generar_todo or payload.generar_mapa_localizacion or payload.generar_mapa_pendientes
    if payload.mapa_base == "carto_positron" and needs_maps and not api_key_efectiva:
        raise HTTPException(status_code=422, detail="Debe indicar la API key de CARTO para generar mapas con Positron.")
    params = payload.model_dump()
    if len(tramos) == 1 and not params.get("carretera"):
        # El formato nuevo con un solo elemento sigue el recorrido single.
        params.update(tramos[0].model_dump())
    params["carto_api_key"] = api_key_efectiva
    job_id = uuid4().hex
    now = datetime.now().isoformat(timespec="seconds")
    with JOBS_LOCK:
        JOBS[job_id] = {
            "job_id": job_id,
            "estado": "pendiente",
            "fase": PROGRESS_PHASES[0],
            "fase_indice": 1,
            "fases_total": len(PROGRESS_PHASES),
            "detalle": "",
            "creado": now,
            "inicio_monotonic": perf_counter(),
            "finalizado": None,
            "resultado": None,
            "error": None,
        }
    EXECUTOR.submit(_run_generation_job, job_id, params)
    return JSONResponse({"job_id": job_id, "estado": "pendiente", "fases_total": len(PROGRESS_PHASES)})


@app.get("/api/carto-api-key")
def carto_api_key_guardada() -> dict[str, bool]:
    return {"stored": bool(obtener_api_key_carto())}


@app.post("/api/carto-api-key/reveal")
def revelar_carto_api_key() -> JSONResponse:
    api_key = obtener_api_key_carto()
    headers = {"Cache-Control": "no-store"}
    if not api_key:
        return JSONResponse({"detail": "No hay una API key guardada."}, status_code=404, headers=headers)
    return JSONResponse({"api_key": api_key}, headers=headers)


@app.delete("/api/carto-api-key")
def olvidar_carto_api_key() -> JSONResponse:
    eliminar_api_key_carto()
    return JSONResponse({"stored": bool(obtener_api_key_carto())}, headers={"Cache-Control": "no-store"})


def _update_job(job_id: str, **updates: Any) -> None:
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(updates)


def _run_generation_job(job_id: str, params: dict[str, Any]) -> None:
    def progress(index: int, phase: str, detail: str | None = None) -> None:
        _update_job(
            job_id,
            estado="ejecutando",
            fase=phase,
            fase_indice=max(1, min(len(PROGRESS_PHASES), int(index))),
            detalle=detail or "",
        )

    try:
        progress(1, PROGRESS_PHASES[0])
        result = generar_outputs(params, progress=progress)
        _update_job(
            job_id,
            estado="completado",
            fase=PROGRESS_PHASES[-1],
            fase_indice=len(PROGRESS_PHASES),
            resultado=result,
            finalizado=datetime.now().isoformat(timespec="seconds"),
        )
    except Exception as exc:
        _update_job(
            job_id,
            estado="error",
            fase="Error de generacion.",
            detalle=str(exc),
            error=str(exc),
            finalizado=datetime.now().isoformat(timespec="seconds"),
        )


@app.get("/api/progreso/{job_id}")
def progreso(job_id: str) -> dict[str, Any]:
    with JOBS_LOCK:
        job = dict(JOBS.get(job_id) or {})
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    start = float(job.pop("inicio_monotonic", perf_counter()))
    job["tiempo_transcurrido_s"] = round(max(0.0, perf_counter() - start), 1)
    return job


@app.get("/outputs/{job_id}/{filename:path}")
def download(job_id: str, filename: str) -> FileResponse:
    outputs_root = resolve_tool_path(load_config().get("paths", {}).get("outputs", "outputs")).resolve()
    target = (outputs_root / job_id / filename).resolve()
    if not _is_within_outputs_root(target, outputs_root):
        raise HTTPException(status_code=404, detail="Archivo no encontrado") from None
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return FileResponse(target, filename=target.name)


def _is_within_outputs_root(target: Path, outputs_root: Path) -> bool:
    try:
        target.relative_to(outputs_root)
    except ValueError:
        return False
    return True


if __name__ == "__main__":
    cfg = load_config().get("app", {})
    uvicorn.run("app:app", host=str(cfg.get("host", "127.0.0.1")), port=int(cfg.get("port", 8025)), reload=False)
