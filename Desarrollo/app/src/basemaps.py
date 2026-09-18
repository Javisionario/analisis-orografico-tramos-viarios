from __future__ import annotations

import math
import re
import urllib.request
from collections import Counter, OrderedDict
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

from PIL import Image, ImageEnhance

from . import USER_AGENT


DEVELOPMENT_ROOT = Path(__file__).resolve().parents[2]
TILE_CACHE = DEVELOPMENT_ROOT / "cache" / "tiles_cartografia"
TILE_TIMEOUT_SECONDS = 6
TILE_SUBDOMAINS = ("a", "b", "c", "d")
MAP_BASE_IGN_GRIS = "ign_gris"
MAP_BASE_CARTO_POSITRON = "carto_positron"
DEFAULT_MAP_BASE = MAP_BASE_IGN_GRIS
TILE_PROVIDERS = {
    MAP_BASE_IGN_GRIS: {
        "nombre": "Callejero gris (IGN)",
        "atribucion": "Instituto Geográfico Nacional de España.",
        "max_native_zoom": 17,
        "tms": True,
    },
    MAP_BASE_CARTO_POSITRON: {
        "nombre": "CARTO Positron",
        "atribucion": "© OpenStreetMap contributors © CARTO",
        "max_native_zoom": 17,
        "tms": False,
    },
}
MAIN_TILE_LAYER = "light_all"
TILE_MIN_ZOOM = 8
TILE_MAX_ZOOM = 17
TILE_ZOOM_DETAIL_BONUS = 0
LOCATION_TILE_ZOOM_OFFSET = -1
TILE_MAX_PER_MAP = 80
TILE_FAILURE_LIMIT = 8
TILE_RETINA_FALLBACK = False
IGN_WMS_URL = "https://www.ign.es/wms-inspire/ign-base"
IGN_WMS_LAYER = "IGNBaseTodo-gris"
IGN_WMS_CRS = "EPSG:3857"
IGN_WMS_DPI = 330
WORLD_MERCATOR_METRES = 40075016.68557849
MAIN_BASEMAP_BRIGHTNESS = -5
MAIN_BASEMAP_SATURATION = 70
MAIN_BASEMAP_GAMMA = 1.5
LOC_BASEMAP_BRIGHTNESS = 0
LOC_BASEMAP_SATURATION = 90
LOC_BASEMAP_GAMMA = 1.2
BASEMAP_RASTER_CACHE_SIZE = 6
BASEMAP_RASTER_CACHE: OrderedDict[tuple[Any, ...], tuple[Image.Image, bool]] = OrderedDict()
TILE_ERRORS: Counter[str] = Counter()
TILE_ERROR_SAMPLES: list[str] = []


def clean(value: Any) -> str:
    return str(value or "").strip()


def mercator(lon: float, lat: float) -> tuple[float, float]:
    clipped = max(min(float(lat), 85.05112878), -85.05112878)
    return (float(lon) + 180.0) / 360.0, (1.0 - math.asinh(math.tan(math.radians(clipped))) / math.pi) / 2.0

def lonlat_from_mercator(x: float, y: float) -> tuple[float, float]:
    lon = x * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y))))
    return lon, lat

def contextily_auto_zoom(bounds: tuple[float, float, float, float]) -> int:
    lon_min, lat_min, lon_max, lat_max = bounds
    lon_length = max(abs(lon_max - lon_min), 1e-9)
    lat_length = max(abs(lat_max - lat_min), 1e-9)
    zoom_lon = math.ceil(math.log2(720.0 / lon_length))
    zoom_lat = math.ceil(math.log2(720.0 / lat_length))
    return int(min(zoom_lon, zoom_lat))

def normalize_map_base(mapa_base: str | None) -> str:
    value = clean(mapa_base).lower()
    return value if value in TILE_PROVIDERS else DEFAULT_MAP_BASE

def tile_provider(mapa_base: str | None) -> dict[str, Any]:
    return TILE_PROVIDERS[normalize_map_base(mapa_base)]

def sanitize_tile_text(value: Any) -> str:
    text = str(value)

    def without_query(match: re.Match[str]) -> str:
        parsed = urlsplit(match.group(0))
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))

    text = re.sub(r"https?://[^\s'\"<>]+", without_query, text)
    return re.sub(r"(?i)(key=)[^&\s]+", r"\1[REDACTED]", text)

def reset_tile_error_state() -> None:
    """Aisla los diagnósticos de teselas de cada generación cartográfica."""
    TILE_ERRORS.clear()
    TILE_ERROR_SAMPLES.clear()

def remember_tile_error(error: Exception, url: str) -> None:
    message = f"{type(error).__name__}: {sanitize_tile_text(error)}"
    TILE_ERRORS[message] += 1
    if len(TILE_ERROR_SAMPLES) < 8:
        TILE_ERROR_SAMPLES.append(f"{sanitize_tile_text(url)} -> {message}")

def remember_failed_tile(tx: int, ty: int, zoom: int, failures: list[tuple[str, Exception]]) -> None:
    if not failures:
        return
    first_url, first_error = failures[0]
    message = f"Tesela {zoom}/{tx}/{ty} fallida: {type(first_error).__name__}: {sanitize_tile_text(first_error)}"
    TILE_ERRORS[message] += 1
    for url, error in failures:
        if len(TILE_ERROR_SAMPLES) >= 8:
            break
        TILE_ERROR_SAMPLES.append(f"{sanitize_tile_text(url)} -> {type(error).__name__}: {sanitize_tile_text(error)}")

def tile_failure_count() -> int:
    return sum(count for message, count in TILE_ERRORS.items() if not message.startswith("Zoom "))

def tile_candidates(
    tx: int,
    ty: int,
    zoom: int,
    mapa_base: str = DEFAULT_MAP_BASE,
    carto_api_key: str | None = None,
    layer: str = MAIN_TILE_LAYER,
    retina: bool = TILE_RETINA_FALLBACK,
) -> Iterable[tuple[str, Path]]:
    provider_key = normalize_map_base(mapa_base)
    if provider_key == MAP_BASE_IGN_GRIS:
        y_tms = 2**zoom - 1 - ty
        url = f"https://tms-ign-base.idee.es/1.0.0/IGNBaseGris/{zoom}/{tx}/{y_tms}.jpeg"
        yield url, TILE_CACHE / f"ign_gris_{zoom}_{tx}_{ty}.jpeg"
        return
    if not clean(carto_api_key):
        return
    suffixes = [("@2x", "_2x"), ("", "_1x")] if retina else [("", "_1x")]
    encoded_key = quote(str(carto_api_key), safe="")
    for suffix, cache_suffix in suffixes:
        for subdomain in TILE_SUBDOMAINS:
            url = f"https://{subdomain}.basemaps.cartocdn.com/rastertiles/{layer}/{zoom}/{tx}/{ty}{suffix}.png?key={encoded_key}"
            cache = TILE_CACHE / f"carto_positron_{layer}_{zoom}_{tx}_{ty}{cache_suffix}.png"
            yield url, cache

def valid_tile_bytes(data: bytes) -> bool:
    return data.startswith(b"\x89PNG") or data.startswith(b"\xff\xd8\xff")

def mercator_metres(lon: float, lat: float) -> tuple[float, float]:
    """Convierte longitud/latitud a EPSG:3857 sin alterar la BBOX del mapa."""
    x, y_from_top = mercator(lon, lat)
    half_world = WORLD_MERCATOR_METRES / 2.0
    return x * WORLD_MERCATOR_METRES - half_world, half_world - y_from_top * WORLD_MERCATOR_METRES

def ign_wms_bbox(bounds: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    lon_min, lat_min, lon_max, lat_max = bounds
    min_x, min_y = mercator_metres(lon_min, lat_min)
    max_x, max_y = mercator_metres(lon_max, lat_max)
    return min_x, min_y, max_x, max_y

def ign_wms_request_url(bounds: tuple[float, float, float, float], width: int, height: int) -> str:
    bbox = ign_wms_bbox(bounds)
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetMap",
        "LAYERS": IGN_WMS_LAYER,
        "STYLES": "",
        "CRS": IGN_WMS_CRS,
        "BBOX": ",".join(f"{value:.12f}" for value in bbox),
        "WIDTH": str(int(width)),
        "HEIGHT": str(int(height)),
        "FORMAT": "image/png",
        "TRANSPARENT": "false",
        "FORMAT_OPTIONS": f"dpi:{IGN_WMS_DPI}",
    }
    return f"{IGN_WMS_URL}?{urlencode(params)}"

def ign_wms_cache_path(bounds: tuple[float, float, float, float], width: int, height: int) -> Path:
    """Caché WMS separada de TMS; la huella incluye BBOX, tamaño, capa y DPI."""
    payload = "|".join(
        [
            "ign_wms",
            IGN_WMS_URL,
            IGN_WMS_LAYER,
            IGN_WMS_CRS,
            *(f"{value:.12f}" for value in ign_wms_bbox(bounds)),
            str(int(width)),
            str(int(height)),
            str(IGN_WMS_DPI),
        ]
    )
    digest = sha256(payload.encode("utf-8")).hexdigest()[:20]
    return TILE_CACHE / f"ign_wms_{IGN_WMS_LAYER}_{IGN_WMS_DPI}_{digest}.png"

def valid_wms_image(data: bytes, width: int, height: int) -> bool:
    if not data.startswith(b"\x89PNG"):
        return False
    try:
        with Image.open(BytesIO(data)) as image:
            image.load()
            return image.format == "PNG" and image.size == (int(width), int(height))
    except Exception:
        return False

def ign_wms_bytes(bounds: tuple[float, float, float, float], width: int, height: int) -> bytes | None:
    """Obtiene el callejero WMS para el clip completo, con caché y validación estricta."""
    try:
        TILE_CACHE.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        remember_tile_error(error, str(TILE_CACHE))
        return None
    cache = ign_wms_cache_path(bounds, width, height)
    try:
        if cache.exists():
            cached = cache.read_bytes()
            if valid_wms_image(cached, width, height):
                return cached
    except Exception as error:
        remember_tile_error(error, str(cache))
    url = ign_wms_request_url(bounds, width, height)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=TILE_TIMEOUT_SECONDS) as response:
            data = response.read()
        if not valid_wms_image(data, width, height):
            raise ValueError("La respuesta WMS no es un PNG valido con las dimensiones solicitadas")
        cache.write_bytes(data)
        return data
    except Exception as error:
        remember_tile_error(error, url)
        return None

def tile_bytes(
    tx: int,
    ty: int,
    zoom: int,
    mapa_base: str = DEFAULT_MAP_BASE,
    carto_api_key: str | None = None,
    layer: str = MAIN_TILE_LAYER,
    retina: bool = TILE_RETINA_FALLBACK,
) -> bytes | None:
    try:
        TILE_CACHE.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        remember_tile_error(error, str(TILE_CACHE))
        return None
    candidates = list(tile_candidates(tx, ty, zoom, mapa_base, carto_api_key, layer, retina))
    for _url, cache in candidates:
        try:
            if cache.exists() and cache.stat().st_size > 0:
                return cache.read_bytes()
        except Exception as error:
            remember_tile_error(error, str(cache))
    if tile_failure_count() >= TILE_FAILURE_LIMIT:
        return None
    failures: list[tuple[str, Exception]] = []
    for url, cache in candidates:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=TILE_TIMEOUT_SECONDS) as response:
                data = response.read()
            if not valid_tile_bytes(data):
                raise ValueError("La respuesta no es una imagen PNG/JPEG valida")
            cache.write_bytes(data)
            return data
        except Exception as error:
            failures.append((url, error))
    remember_failed_tile(tx, ty, zoom, failures)
    return None

def tile_layout_for_zoom(
    bounds: tuple[float, float, float, float],
    x: float,
    y: float,
    width: float,
    height: float,
    zoom: int,
) -> tuple[int, list[tuple[int, int, float, float, float, float]], int]:
    lon_min, lat_min, lon_max, lat_max = bounds
    x0, y1 = mercator(lon_min, lat_min)
    x1, y0 = mercator(lon_max, lat_max)
    zoom = max(TILE_MIN_ZOOM, min(TILE_MAX_ZOOM, int(zoom)))
    world = 256 * (2**zoom)
    denominator_x = max(x1 * world - x0 * world, 1e-9)
    denominator_y = max(y1 * world - y0 * world, 1e-9)
    tx_range = range(math.floor(x0 * world / 256), math.floor(x1 * world / 256) + 1)
    ty_range = range(math.floor(y0 * world / 256), math.floor(y1 * world / 256) + 1)
    tiles = []
    for tx in tx_range:
        for ty in ty_range:
            left = x + (tx * 256 - x0 * world) / denominator_x * width
            top = y + (ty * 256 - y0 * world) / denominator_y * height
            tile_w = 256 / denominator_x * width
            tile_h = 256 / denominator_y * height
            tiles.append((tx, ty, left, top, tile_w, tile_h))
    return zoom, tiles, max(len(tiles), 1)

def tile_layout(
    bounds: tuple[float, float, float, float],
    x: float,
    y: float,
    width: float,
    height: float,
    zoom_offset: int = 0,
) -> tuple[int, list[tuple[int, int, float, float, float, float]], int]:
    lon_min, lat_min, lon_max, lat_max = bounds
    x0, y1 = mercator(lon_min, lat_min)
    x1, y0 = mercator(lon_max, lat_max)
    zoom = max(TILE_MIN_ZOOM, min(TILE_MAX_ZOOM, contextily_auto_zoom(bounds) + TILE_ZOOM_DETAIL_BONUS + int(zoom_offset)))
    while zoom > TILE_MIN_ZOOM:
        world = 256 * (2**zoom)
        tx_count = math.floor(x1 * world / 256) - math.floor(x0 * world / 256) + 1
        ty_count = math.floor(y1 * world / 256) - math.floor(y0 * world / 256) + 1
        if tx_count * ty_count <= TILE_MAX_PER_MAP:
            break
        TILE_ERRORS[f"Zoom {zoom} reducido por exceso de teselas ({tx_count * ty_count})"] += 1
        zoom -= 1
    return tile_layout_for_zoom(bounds, x, y, width, height, zoom)

def tile_layout_fallbacks(
    bounds: tuple[float, float, float, float],
    x: float,
    y: float,
    width: float,
    height: float,
    zoom_offset: int = 0,
) -> Iterable[tuple[int, list[tuple[int, int, float, float, float, float]], int]]:
    zoom, layout, required_tiles = tile_layout(bounds, x, y, width, height, zoom_offset)
    yield zoom, layout, required_tiles
    for fallback_zoom in range(zoom - 1, TILE_MIN_ZOOM - 1, -1):
        yield tile_layout_for_zoom(bounds, x, y, width, height, fallback_zoom)

def paste_tile(canvas: Image.Image, tile: Image.Image, left: float, top: float, tile_w: float, tile_h: float, clip: tuple[int, int, int, int]) -> bool:
    resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS", 1)
    resized = tile.resize((max(1, int(round(tile_w))), max(1, int(round(tile_h)))), resampling)
    dest_x, dest_y = int(round(left)), int(round(top))
    x0 = max(dest_x, clip[0])
    y0 = max(dest_y, clip[1])
    x1 = min(dest_x + resized.width, clip[0] + clip[2])
    y1 = min(dest_y + resized.height, clip[1] + clip[3])
    if x1 <= x0 or y1 <= y0:
        return False
    crop = resized.crop((x0 - dest_x, y0 - dest_y, x1 - dest_x, y1 - dest_y))
    canvas.alpha_composite(crop, (x0, y0))
    return True

def adjust_tile_image(tile: Image.Image, brightness: float, saturation: float, gamma: float) -> Image.Image:
    image = tile.convert("RGBA")
    if abs(float(saturation)) > 1e-9:
        image = ImageEnhance.Color(image).enhance(max(0.0, 1.0 + float(saturation) / 100.0))
    if abs(float(brightness)) > 1e-9:
        image = ImageEnhance.Brightness(image).enhance(max(0.0, 1.0 + float(brightness) / 100.0))
    gamma_value = max(float(gamma), 1e-6)
    if abs(gamma_value - 1.0) > 1e-9:
        lut = [int(max(0, min(255, ((i / 255.0) ** gamma_value) * 255.0))) for i in range(256)]
        image = image.point(lut * 3 + list(range(256)))
    return image

def basemap_raster(
    bounds: tuple[float, float, float, float],
    canvas: Image.Image,
    clip: tuple[int, int, int, int],
    brightness: float = MAIN_BASEMAP_BRIGHTNESS,
    saturation: float = MAIN_BASEMAP_SATURATION,
    gamma: float = MAIN_BASEMAP_GAMMA,
    mapa_base: str = DEFAULT_MAP_BASE,
    carto_api_key: str | None = None,
    tile_layer: str = MAIN_TILE_LAYER,
    retina: bool = TILE_RETINA_FALLBACK,
    zoom_offset: int = 0,
) -> bool:
    provider_key = normalize_map_base(mapa_base)
    key = tuple(round(value, 5) for value in bounds) + (
        clip[2],
        clip[3],
        int(brightness),
        int(saturation),
        int(gamma * 100),
        provider_key,
        tile_layer,
        int(retina),
        int(zoom_offset),
    )
    if key in BASEMAP_RASTER_CACHE:
        cached, ok = BASEMAP_RASTER_CACHE.pop(key)
        BASEMAP_RASTER_CACHE[key] = (cached, ok)
        canvas.alpha_composite(cached.copy(), (clip[0], clip[1]))
        return ok
    best_layer = Image.new("RGBA", (clip[2], clip[3]), "#eef1ed")
    best_loaded = -1
    ok = False
    for zoom, layout, required_tiles in tile_layout_fallbacks(bounds, clip[0], clip[1], clip[2], clip[3], zoom_offset):
        layer = Image.new("RGBA", (clip[2], clip[3]), "#eef1ed")
        loaded = 0
        for tx, ty, left, top, tile_w, tile_h in layout:
            data = tile_bytes(tx, ty, zoom, provider_key, carto_api_key, tile_layer, retina)
            if not data:
                continue
            try:
                tile = adjust_tile_image(Image.open(BytesIO(data)).convert("RGBA"), brightness, saturation, gamma)
                if paste_tile(layer, tile, left - clip[0], top - clip[1], tile_w, tile_h, (0, 0, clip[2], clip[3])):
                    loaded += 1
            except Exception as error:
                remember_tile_error(error, f"tile {zoom}/{tx}/{ty}")
        if loaded > best_loaded:
            best_layer = layer
            best_loaded = loaded
        if loaded == required_tiles:
            ok = True
            best_layer = layer
            break
    if ok:
        BASEMAP_RASTER_CACHE[key] = (best_layer.copy(), ok)
        BASEMAP_RASTER_CACHE.move_to_end(key)
        while len(BASEMAP_RASTER_CACHE) > BASEMAP_RASTER_CACHE_SIZE:
            BASEMAP_RASTER_CACHE.popitem(last=False)
    canvas.alpha_composite(best_layer, (clip[0], clip[1]))
    return ok

def ign_wms_basemap_raster(
    bounds: tuple[float, float, float, float],
    canvas: Image.Image,
    clip: tuple[int, int, int, int],
    brightness: float,
    saturation: float,
    gamma: float,
) -> bool:
    """Compone el WMS IGN a tamaño nativo del clip, sin reescalarlo ni teselarlo."""
    key = tuple(f"{value:.12f}" for value in ign_wms_bbox(bounds)) + (
        clip[2],
        clip[3],
        int(brightness),
        int(saturation),
        int(gamma * 100),
        "ign_wms",
        IGN_WMS_LAYER,
        IGN_WMS_CRS,
        IGN_WMS_DPI,
    )
    if key in BASEMAP_RASTER_CACHE:
        cached, ok = BASEMAP_RASTER_CACHE.pop(key)
        BASEMAP_RASTER_CACHE[key] = (cached, ok)
        canvas.alpha_composite(cached.copy(), (clip[0], clip[1]))
        return ok
    data = ign_wms_bytes(bounds, clip[2], clip[3])
    if not data:
        return False
    try:
        with Image.open(BytesIO(data)) as raw:
            raw.load()
            layer = adjust_tile_image(raw.convert("RGBA"), brightness, saturation, gamma)
    except Exception as error:
        remember_tile_error(error, "IGN WMS")
        return False
    if layer.size != (clip[2], clip[3]):
        remember_tile_error(ValueError("El WMS no coincide con el clip solicitado"), "IGN WMS")
        return False
    BASEMAP_RASTER_CACHE[key] = (layer.copy(), True)
    BASEMAP_RASTER_CACHE.move_to_end(key)
    while len(BASEMAP_RASTER_CACHE) > BASEMAP_RASTER_CACHE_SIZE:
        BASEMAP_RASTER_CACHE.popitem(last=False)
    canvas.alpha_composite(layer, (clip[0], clip[1]))
    return True

def render_report_basemap(
    bounds: tuple[float, float, float, float],
    canvas: Image.Image,
    clip: tuple[int, int, int, int],
    config: dict[str, Any] | None = None,
    location: bool = False,
    mapa_base: str = DEFAULT_MAP_BASE,
    carto_api_key: str | None = None,
) -> bool:
    provider_key = normalize_map_base(mapa_base)
    provider = tile_provider(provider_key)
    brightness = LOC_BASEMAP_BRIGHTNESS if location else MAIN_BASEMAP_BRIGHTNESS
    saturation = LOC_BASEMAP_SATURATION if location else MAIN_BASEMAP_SATURATION
    gamma = LOC_BASEMAP_GAMMA if location else MAIN_BASEMAP_GAMMA
    zoom_offset = LOCATION_TILE_ZOOM_OFFSET if location else 0
    method = "tms"
    fallback_used = False
    if provider_key == MAP_BASE_IGN_GRIS:
        method = "wms"
        ok = ign_wms_basemap_raster(bounds, canvas, clip, brightness, saturation, gamma)
        if not ok:
            fallback_used = True
            method = "tms_fallback"
            ok = basemap_raster(bounds, canvas, clip, brightness, saturation, gamma, provider_key, carto_api_key, MAIN_TILE_LAYER, TILE_RETINA_FALLBACK, zoom_offset)
    else:
        ok = basemap_raster(bounds, canvas, clip, brightness, saturation, gamma, provider_key, carto_api_key, MAIN_TILE_LAYER, TILE_RETINA_FALLBACK, zoom_offset)
    if isinstance(config, dict):
        config["proveedor"] = provider["nombre"]
        config["atribucion"] = provider["atribucion"]
        config["tms"] = provider["tms"]
        config["max_native_zoom"] = provider["max_native_zoom"]
        config["zoom_offset"] = zoom_offset
        config["metodo"] = method
        config["fallback_tms_usado"] = fallback_used
        if provider_key == MAP_BASE_IGN_GRIS:
            config["wms"] = {
                "url": IGN_WMS_URL,
                "capa": IGN_WMS_LAYER,
                "crs": IGN_WMS_CRS,
                "dpi": IGN_WMS_DPI,
                "width": clip[2],
                "height": clip[3],
                "bbox_3857": list(ign_wms_bbox(bounds)),
            }
        if provider_key == MAP_BASE_CARTO_POSITRON:
            config["capa"] = MAIN_TILE_LAYER
        config["ok"] = ok
    return ok
