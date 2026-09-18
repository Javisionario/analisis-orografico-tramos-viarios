from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import numpy as np
import rasterio
import requests
from owslib.wcs import WebCoverageService
from rasterio.merge import merge

from .utils import ensure_dir, resolve_tool_path
from . import USER_AGENT


WCS_VERSION = "1.0.0"
WCS_FORMAT = "GEOTIFFINT16"
PREFERRED_COVERAGES = {
    5: "Elevacion4258_5",
    25: "Elevacion4258_25",
}
TILE_SIZE_PX = 1024


@dataclass
class MdtResult:
    path: Path | None
    coverage_id: str | None
    resolution_m: float | None
    source: str
    warnings: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)


def _clean_wcs_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _coverage_candidates(url: str, timeout: int, preferred_resolution: float, warnings: list[str]) -> list[str]:
    preferred = PREFERRED_COVERAGES.get(preferred_resolution)
    if not preferred:
        warnings.append(f"No hay cobertura WCS configurada para resolución {preferred_resolution:g} m.")
        return []
    try:
        wcs = WebCoverageService(url, version=WCS_VERSION, timeout=timeout)
        discovered = set(wcs.contents.keys())
        if preferred not in discovered:
            warnings.append(f"GetCapabilities no anuncia la cobertura esperada {preferred} para {preferred_resolution:g} m.")
    except Exception as exc:
        warnings.append(f"No se pudo consultar GetCapabilities WCS; se prueba la cobertura esperada {preferred}: {exc}")
    # Cada tentativa de resolución usa exclusivamente su coverage equivalente.
    return [preferred]


def _cache_path(cache_dir: Path, bbox: tuple[float, float, float, float], epsg: int, resolution: float, coverage_id: str) -> Path:
    key = {
        "bbox": [round(v, 2) for v in bbox],
        "epsg": epsg,
        "resolution": resolution,
        "coverage_id": coverage_id,
        "format": WCS_FORMAT,
        "version": WCS_VERSION,
    }
    digest = hashlib.sha1(repr(key).encode("utf-8")).hexdigest()[:18]
    return cache_dir / f"mdt_{digest}.tif"


def _dimensions(bbox: tuple[float, float, float, float], resolution: float) -> tuple[int, int]:
    width = max(1, int(math.ceil((bbox[2] - bbox[0]) / max(resolution, 1e-9))))
    height = max(1, int(math.ceil((bbox[3] - bbox[1]) / max(resolution, 1e-9))))
    return width, height


def _resolution_attempts(
    bbox: tuple[float, float, float, float], resolutions: list[float], max_pixels: int
) -> list[dict[str, int | float | bool]]:
    """Calcula el coste de cada resolución antes de abrir conexiones WCS."""
    attempts: list[dict[str, int | float | bool]] = []
    for resolution in resolutions:
        width, height = _dimensions(bbox, resolution)
        pixels = width * height
        attempts.append(
            {
                "resolution": float(resolution),
                "width": width,
                "height": height,
                "pixels": pixels,
                "within_limit": pixels <= max_pixels,
            }
        )
    return attempts


def _supported_resolutions(
    resolution_preference: str | float | None, mdt_cfg: dict[str, Any], warnings: list[str]
) -> list[float]:
    supported = {float(value) for value in PREFERRED_COVERAGES}
    if str(resolution_preference or "5").lower() == "auto":
        configured = [float(value) for value in mdt_cfg.get("resoluciones_preferidas_m", [5, 25])]
        resolutions = [value for value in configured if value in supported]
        if not resolutions:
            warnings.append("No hay resoluciones WCS nativas válidas configuradas; se usan 5 m y 25 m.")
            return [5.0, 25.0]
        return list(dict.fromkeys(resolutions))
    try:
        preferred = float(resolution_preference)
    except (TypeError, ValueError):
        preferred = None
    if preferred not in supported:
        warnings.append(f"Resolución MDT no compatible ({resolution_preference}); se usan 5 m y 25 m.")
        return [5.0, 25.0]
    return [preferred, 25.0] if preferred == 5.0 else [preferred]


def _params(
    bbox: tuple[float, float, float, float],
    epsg: int,
    coverage_id: str,
    width: int,
    height: int,
) -> dict[str, str]:
    return {
        "SERVICE": "WCS",
        "VERSION": WCS_VERSION,
        "REQUEST": "GetCoverage",
        "FORMAT": WCS_FORMAT,
        "COVERAGE": coverage_id,
        "BBOX": ",".join(f"{value:.8f}" for value in bbox),
        "CRS": f"EPSG:{epsg}",
        "RESPONSE_CRS": f"EPSG:{epsg}",
        "WIDTH": str(int(width)),
        "HEIGHT": str(int(height)),
    }


def _looks_like_tiff(data: bytes) -> bool:
    return data.startswith(b"II*\x00") or data.startswith(b"MM\x00*")


def _response_diag(response: requests.Response, data: bytes) -> dict[str, Any]:
    content_type = response.headers.get("Content-Type", "")
    diag: dict[str, Any] = {
        "url": response.url,
        "status_code": response.status_code,
        "content_type": content_type,
        "bytes": len(data),
    }
    if data and not _looks_like_tiff(data):
        try:
            diag["primeros_300_caracteres"] = data[:300].decode("utf-8", errors="replace")
        except Exception:
            diag["primeros_300_caracteres"] = repr(data[:80])
    return diag


def _validate_tiff(path: Path) -> tuple[bool, dict[str, Any], str | None]:
    try:
        with rasterio.open(path) as src:
            if src.width <= 0 or src.height <= 0:
                return False, {}, "raster sin dimensiones validas"
            if src.crs is None:
                return False, {}, "raster sin CRS"
            if src.transform is None:
                return False, {}, "raster sin transformacion valida"
            out_h = min(64, src.height)
            out_w = min(64, src.width)
            data = src.read(1, masked=True, out_shape=(out_h, out_w))
            values = data.compressed() if np.ma.isMaskedArray(data) else data.ravel()
            values = values[np.isfinite(values)]
            if values.size == 0:
                return False, {}, "raster sin valores finitos en muestra"
            meta = {
                "mdt_crs": str(src.crs),
                "mdt_bounds": list(src.bounds),
                "mdt_width": int(src.width),
                "mdt_height": int(src.height),
                "mdt_nodata": None if src.nodata is None else float(src.nodata),
                "mdt_min_muestra": float(np.nanmin(values)),
                "mdt_max_muestra": float(np.nanmax(values)),
            }
            return True, meta, None
    except Exception as exc:
        return False, {}, f"no se pudo abrir GeoTIFF con rasterio: {exc}"


def _download_one(
    url: str,
    cache_path: Path,
    bbox: tuple[float, float, float, float],
    epsg: int,
    coverage_id: str,
    resolution: float,
    timeout: int,
    headers: dict[str, str],
) -> tuple[Path | None, dict[str, Any], str | None]:
    width, height = _dimensions(bbox, resolution)
    params = _params(bbox, epsg, coverage_id, width, height)
    try:
        response = requests.get(url, params=params, timeout=timeout, headers=headers)
    except requests.RequestException as exc:
        return None, {
            "coverage": coverage_id,
            "format": WCS_FORMAT,
            "crs_peticion": f"EPSG:{epsg}",
            "response_crs": f"EPSG:{epsg}",
            "resolution": float(resolution),
            "width": int(width),
            "height": int(height),
            "params": params,
            "request_error": str(exc),
        }, f"error de red WCS: {exc}"
    data = response.content or b""
    diag = {
        "coverage": coverage_id,
        "format": WCS_FORMAT,
        "crs_peticion": f"EPSG:{epsg}",
        "response_crs": f"EPSG:{epsg}",
        "resolution": float(resolution),
        "width": int(width),
        "height": int(height),
        "params": params,
        "response": _response_diag(response, data),
    }
    content_type = response.headers.get("Content-Type", "").lower()
    content_ok = any(token in content_type for token in ("tiff", "geotiff", "octet-stream"))
    if response.status_code != 200:
        return None, diag, f"HTTP {response.status_code}"
    if not content_ok:
        return None, diag, f"Content-Type no compatible: {content_type or 'sin content-type'}"
    if not data or len(data) < 1024:
        return None, diag, "respuesta WCS vacia o demasiado corta"
    if not _looks_like_tiff(data):
        return None, diag, "respuesta WCS no parece TIFF"

    tmp_path = cache_path.with_name(f"{cache_path.stem}.tmp.tif")
    tmp_path.write_bytes(data)
    ok, raster_meta, validation_error = _validate_tiff(tmp_path)
    if not ok:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        return None, diag, validation_error
    tmp_path.replace(cache_path)
    diag.update(raster_meta)
    return cache_path, diag, None


def _tile_bboxes(
    bbox: tuple[float, float, float, float],
    resolution: float,
    tile_size: int,
) -> list[tuple[tuple[float, float, float, float], int, int]]:
    width, height = _dimensions(bbox, resolution)
    cols = max(1, math.ceil(width / tile_size))
    rows = max(1, math.ceil(height / tile_size))
    tiles: list[tuple[tuple[float, float, float, float], int, int]] = []
    for row in range(rows):
        for col in range(cols):
            x0 = bbox[0] + col * tile_size * resolution
            x1 = min(bbox[2], bbox[0] + (col + 1) * tile_size * resolution)
            y0 = bbox[1] + row * tile_size * resolution
            y1 = min(bbox[3], bbox[1] + (row + 1) * tile_size * resolution)
            tiles.append(((x0, y0, x1, y1), row, col))
    return tiles


def _download_tiled(
    url: str,
    cache_path: Path,
    bbox: tuple[float, float, float, float],
    epsg: int,
    coverage_id: str,
    resolution: float,
    timeout: int,
    headers: dict[str, str],
    tile_size: int,
) -> tuple[Path | None, dict[str, Any], list[str]]:
    warnings: list[str] = []
    tiles = _tile_bboxes(bbox, resolution, tile_size)
    tile_paths: list[Path] = []
    tile_errors = 0
    diagnostics: list[dict[str, Any]] = []
    for tile_bbox, row, col in tiles:
        tile_path = cache_path.with_name(f"{cache_path.stem}_tile_{row}_{col}.tif")
        if tile_path.exists():
            ok, raster_meta, validation_error = _validate_tiff(tile_path)
            if ok:
                tile_paths.append(tile_path)
                diagnostics.append({"row": row, "col": col, "cache": True, **raster_meta})
                continue
            try:
                tile_path.unlink(missing_ok=True)
            except Exception:
                pass
            warnings.append(f"Tile WCS cache invalido {row},{col}: {validation_error}")
        path, diag, error = _download_one(url, tile_path, tile_bbox, epsg, coverage_id, resolution, timeout, headers)
        diag.update({"row": row, "col": col})
        diagnostics.append(diag)
        if path:
            tile_paths.append(path)
        else:
            tile_errors += 1
            warnings.append(f"Tile WCS {row},{col} fallo: {error}")

    meta: dict[str, Any] = {
        "wcs_modo_descarga": "teselada",
        "wcs_tile_width": int(tile_size),
        "wcs_tile_height": int(tile_size),
        "n_tiles": len(tiles),
        "n_tiles_ok": len(tile_paths),
        "n_tiles_error": tile_errors,
        "tile_diagnostics": diagnostics[:8],
    }
    if not tile_paths or tile_errors:
        return None, meta, warnings

    datasets = [rasterio.open(path) for path in tile_paths]
    try:
        mosaic, transform = merge(datasets)
        out_meta = datasets[0].meta.copy()
        out_meta.update({
            "driver": "GTiff",
            "height": mosaic.shape[1],
            "width": mosaic.shape[2],
            "transform": transform,
        })
        tmp_path = cache_path.with_name(f"{cache_path.stem}.tmp.tif")
        with rasterio.open(tmp_path, "w", **out_meta) as dst:
            dst.write(mosaic)
        ok, raster_meta, validation_error = _validate_tiff(tmp_path)
        if not ok:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            warnings.append(f"Mosaico WCS invalido: {validation_error}")
            return None, meta, warnings
        tmp_path.replace(cache_path)
        meta.update(raster_meta)
        return cache_path, meta, warnings
    finally:
        for dataset in datasets:
            dataset.close()


def _probe_small(
    url: str,
    bbox: tuple[float, float, float, float],
    epsg: int,
    coverage_id: str,
    resolution: float,
    timeout: int,
    headers: dict[str, str],
    cache_dir: Path,
) -> dict[str, Any]:
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    half = 25.0
    probe_bbox = (cx - half, cy - half, cx + half, cy + half)
    probe_path = cache_dir / f"probe_{coverage_id}_{epsg}.tif"
    path, diag, error = _download_one(url, probe_path, probe_bbox, epsg, coverage_id, resolution, timeout, headers)
    if path:
        try:
            probe_path.unlink(missing_ok=True)
        except Exception:
            pass
    return {"ok": bool(path), "error": error, "diagnostico": diag}


def obtener_mdt(
    config: dict[str, Any],
    bbox: tuple[float, float, float, float],
    epsg: int,
    resolution_preference: str | float | None,
) -> MdtResult:
    warnings: list[str] = []
    mdt_cfg = config.get("mdt", {})
    cache_dir = ensure_dir(resolve_tool_path(config.get("paths", {}).get("cache_mdt", "cache/mdt")))
    resolutions = _supported_resolutions(resolution_preference, mdt_cfg, warnings)

    url = _clean_wcs_url(str(mdt_cfg.get("wcs_url", "")))
    timeout = int(mdt_cfg.get("timeout_s", 45))
    max_pixels = max(1, int(mdt_cfg.get("max_pixeles", 4_000_000)))
    attempts = _resolution_attempts(bbox, resolutions, max_pixels)
    headers = {"User-Agent": USER_AGENT}
    base_meta: dict[str, Any] = {
        "wcs_url": url,
        "wcs_version": WCS_VERSION,
        "coverage_preferida": PREFERRED_COVERAGES.get(resolutions[0]) if resolutions else None,
        "format_preferido": WCS_FORMAT,
        "crs_peticion": f"EPSG:{epsg}",
        "response_crs": f"EPSG:{epsg}",
        "resolucion_solicitada": None if resolution_preference is None else str(resolution_preference),
        "bbox": list(bbox),
        "max_pixeles": max_pixels,
        "intentos_resolucion": attempts,
    }
    if not url:
        return MdtResult(None, None, None, "sin_wcs", ["No hay URL WCS configurada."], base_meta)

    last_diag: dict[str, Any] = {}
    skipped_for_pixel_limit = False
    for attempt in attempts:
        resolution = float(attempt["resolution"])
        if resolution != resolutions[0]:
            reason = "por límite de tamaño/coste" if skipped_for_pixel_limit else "por fallo de la tentativa anterior"
            warnings.append(f"Se intenta MDT a {resolution:g} m {reason}.")
        width = int(attempt["width"])
        height = int(attempt["height"])
        pixels = int(attempt["pixels"])
        if not bool(attempt["within_limit"]):
            skipped_for_pixel_limit = True
            warning = (
                f"MDT a {resolution:g} m no se solicita: {width} x {height} = {pixels} píxeles "
                f"supera el límite configurado de {max_pixels}."
            )
            warnings.append(warning)
            last_diag = {
                **base_meta,
                "coverage_preferida": PREFERRED_COVERAGES.get(resolution),
                "resolucion_usada": float(resolution),
                "width": width,
                "height": height,
                "pixels_solicitados": pixels,
                "descartado_por_max_pixeles": True,
            }
            continue
        coverages = _coverage_candidates(url, timeout, resolution, warnings)
        for coverage_id in coverages:
            cache = _cache_path(cache_dir, bbox, epsg, resolution, coverage_id)
            meta = {
                **base_meta,
                "coverage_preferida": PREFERRED_COVERAGES.get(resolution),
                "coverage_usada": coverage_id,
                "format_usado": WCS_FORMAT,
                "resolucion_usada": float(resolution),
                "width": width,
                "height": height,
                "pixels_solicitados": pixels,
                "resolucion_degradada_por_max_pixeles": skipped_for_pixel_limit,
            }
            if cache.exists():
                ok, raster_meta, validation_error = _validate_tiff(cache)
                if ok:
                    return MdtResult(cache, coverage_id, resolution, "cache", warnings, {**meta, **raster_meta, "wcs_modo_descarga": "cache"})
                try:
                    cache.unlink(missing_ok=True)
                except Exception:
                    pass
                warnings.append(f"Cache MDT invalida descartada para {coverage_id}: {validation_error}")

            tile_size = int(mdt_cfg.get("wcs_tile_size_px", TILE_SIZE_PX))
            if width > tile_size or height > tile_size:
                path, tile_meta, tile_warnings = _download_tiled(url, cache, bbox, epsg, coverage_id, resolution, timeout, headers, tile_size)
                warnings.extend(tile_warnings)
                last_diag = {**meta, **tile_meta}
                if path:
                    return MdtResult(path, coverage_id, resolution, "wcs", warnings, last_diag)
            else:
                path, diag, error = _download_one(url, cache, bbox, epsg, coverage_id, resolution, timeout, headers)
                last_diag = {**meta, "wcs_modo_descarga": "directa", "ultimo_diagnostico": diag}
                if path:
                    return MdtResult(path, coverage_id, resolution, "wcs", warnings, {**last_diag, **diag})
                warnings.append(f"WCS fallo para coverage={coverage_id} resolucion={resolution:g} m: {error}")
                path, tile_meta, tile_warnings = _download_tiled(url, cache, bbox, epsg, coverage_id, resolution, timeout, headers, tile_size)
                warnings.extend(tile_warnings)
                last_diag = {**meta, **tile_meta, "fallo_descarga_directa": error, "ultimo_diagnostico_directo": diag}
                if path:
                    return MdtResult(path, coverage_id, resolution, "wcs", warnings, last_diag)

            probe = _probe_small(url, bbox, epsg, coverage_id, resolution, timeout, headers, cache_dir)
            last_diag["wcs_probe_10x10"] = probe
            if probe.get("ok"):
                warnings.append(f"La prueba WCS pequena funciona para {coverage_id}, pero no se obtuvo raster completo valido.")

    return MdtResult(None, None, None, "no_disponible", warnings or ["No se pudo descargar MDT desde WCS."], {**base_meta, **last_diag})
