from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Any
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from starlette.requests import Request

from src import APP_VERSION
from src.exportacion import generar_outputs
from src.credenciales import eliminar_api_key_carto, guardar_api_key_carto, obtener_api_key_carto
from src.io_datos import diagnostico_capas, list_road_options, load_lineas, resolve_road_name
from src.tramo import ajustar_pk_a_rango, rango_disponible_sentido
from src.utils import load_config, resolve_tool_path


ROOT = Path(__file__).resolve().parent
app = FastAPI(title="Herramienta tramos y pendientes", version=APP_VERSION)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")
# El compositor mantiene diagnósticos por generación; serializar jobs evita cruzarlos.
EXECUTOR = ThreadPoolExecutor(max_workers=1)
JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = Lock()

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


class GenerarRequest(BaseModel):
    carretera: str
    pk_inicio: float
    pk_fin: float
    sentido: str = "creciente"
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


@app.post("/generar")
def generar(payload: GenerarRequest) -> JSONResponse:
    if payload.mapa_base not in {"ign_gris", "carto_positron"}:
        raise HTTPException(status_code=422, detail="Mapa base no valido.")
    api_key_introducida = str(payload.carto_api_key or "").strip()
    if api_key_introducida and payload.recordar_carto_api_key:
        guardar_api_key_carto(api_key_introducida)
    api_key_efectiva = api_key_introducida or obtener_api_key_carto()
    needs_maps = payload.generar_todo or payload.generar_mapa_localizacion or payload.generar_mapa_pendientes
    if payload.mapa_base == "carto_positron" and needs_maps and not api_key_efectiva:
        raise HTTPException(status_code=422, detail="Debe indicar la API key de CARTO para generar mapas con Positron.")
    params = payload.model_dump()
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
