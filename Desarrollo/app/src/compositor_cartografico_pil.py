from __future__ import annotations

import math
import re
import urllib.request
from hashlib import sha256
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from collections import Counter, OrderedDict
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Iterable

from PIL import Image, ImageDraw, ImageEnhance, ImageFont


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
# El recuadro de localización necesita una cartografía más generalizada que el mapa principal.
LOCATION_TILE_ZOOM_OFFSET = -1
TILE_MAX_PER_MAP = 80
TILE_FAILURE_LIMIT = 8
TILE_RETINA_FALLBACK = False
IGN_WMS_URL = "https://www.ign.es/wms-inspire/ign-base"
IGN_WMS_LAYER = "IGNBaseTodo-gris"
IGN_WMS_CRS = "EPSG:3857"
IGN_WMS_DPI = 330

MAP_DPI = 600
WORLD_MERCATOR_METRES = 40075016.68557849
MAIN_BASEMAP_BRIGHTNESS = -5
MAIN_BASEMAP_SATURATION = 70
MAIN_BASEMAP_GAMMA = 1.5
LOC_BASEMAP_BRIGHTNESS = 0
LOC_BASEMAP_SATURATION = 90
LOC_BASEMAP_GAMMA = 1.2

INK = "#162c43"
MUTED = "#526273"
FONT = "Segoe UI, Helvetica, Arial, sans-serif"

OUTPUT_WIDTH_CM = 17.0
OUTPUT_HEIGHT_CM = 12.0
INNER_MARGIN_CM = 0.2
COLUMN_GAP_CM = 0.3
LEFT_BLOCK_WIDTH_CM = 4.45
LOCATION_MAP_HEIGHT_CM = 4.05
LOCATION_SCALE_APPROX = 5_000_000
LOCATION_MIN_WIDTH_M = 200_000
MAP_PX_PER_CM = MAP_DPI / 2.54
LEFT_X_CM = INNER_MARGIN_CM
MAIN_X_CM = LEFT_X_CM + LEFT_BLOCK_WIDTH_CM + COLUMN_GAP_CM
MAIN_W_CM = OUTPUT_WIDTH_CM - MAIN_X_CM - INNER_MARGIN_CM
MAIN_H_CM = OUTPUT_HEIGHT_CM - 2 * INNER_MARGIN_CM
MAP_WIDTH = int(OUTPUT_WIDTH_CM * MAP_PX_PER_CM)
MAP_HEIGHT = int(OUTPUT_HEIGHT_CM * MAP_PX_PER_CM)
MAP_MAIN = (
    int(MAIN_X_CM * MAP_PX_PER_CM),
    int(INNER_MARGIN_CM * MAP_PX_PER_CM),
    int(MAIN_W_CM * MAP_PX_PER_CM),
    int(MAIN_H_CM * MAP_PX_PER_CM),
)
MAP_INSET = (
    int(LEFT_X_CM * MAP_PX_PER_CM),
    int(INNER_MARGIN_CM * MAP_PX_PER_CM),
    int(LEFT_BLOCK_WIDTH_CM * MAP_PX_PER_CM),
    int(LOCATION_MAP_HEIGHT_CM * MAP_PX_PER_CM),
)

PK_TICK_HALF_LENGTH = 22.0
PK_TICK_WIDTH = 5
PK_LABEL_FONT_SIZE = 60
PK_LABEL_OFFSET_SCALE = 1.20
PK_CALLOUT_WIDTH = 3
PK_ALLOWED_INTERVALS = (1, 5, 10, 25, 50, 100, 250)

MAP_TITLE_FONT_SIZE = 72
MAP_SUBTITLE_FONT_SIZE = 70
MAP_LEGEND_FONT_SIZE = 68
MAP_LEGEND_FALLBACK_FONT_SIZE = 60
MAP_LEGEND_WRAP_CHARS = 26
MAP_LEGEND_Y_OFFSET_CM = 0.24
MAP_LEGEND_LINE_STEP_PX = 76
MAP_LEGEND_HEADING_STEP_PX = 132
MAP_LEGEND_ROW_MIN_PX = 132
MAP_LEGEND_FALLBACK_LINE_STEP_PX = 68
MAP_LEGEND_FALLBACK_ROW_MIN_PX = 116
MAP_LEGEND_SCALE_MIN_GAP_PX = 52
MAP_SCALE_FONT_SIZE = 63
MAP_SCALE_LABEL_OFFSET_CM = 0.48
MAP_SCALE_BOTTOM_MARGIN_CM = 0.05
MAP_TITLE_SUBTITLE_GAP_CM = 0.62
MAP_SUBTITLE_LINE_STEP_CM = 0.48
MAP_SCALE_TEXT_PAD_CM = MAP_SCALE_LABEL_OFFSET_CM
MAP_OUTPUT_BORDER_COLOR = "#c8c8c8"
MAP_OUTPUT_BORDER_WIDTH = 4

BASEMAP_RASTER_CACHE_SIZE = 6
BASEMAP_RASTER_CACHE: OrderedDict[tuple[Any, ...], tuple[Image.Image, bool]] = OrderedDict()
TILE_ERRORS: Counter[str] = Counter()
TILE_ERROR_SAMPLES: list[str] = []


def cm_px(value: float) -> int:
    return int(round(value * MAP_PX_PER_CM))


def pil_width(value: float | int) -> int:
    return max(1, int(round(float(value))))


def clean(value: Any) -> str:
    return str(value or "").strip()


def mercator(lon: float, lat: float) -> tuple[float, float]:
    clipped = max(min(float(lat), 85.05112878), -85.05112878)
    return (float(lon) + 180.0) / 360.0, (1.0 - math.asinh(math.tan(math.radians(clipped))) / math.pi) / 2.0


def lonlat_from_mercator(x: float, y: float) -> tuple[float, float]:
    lon = x * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y))))
    return lon, lat


def fit_bounds_to_clip(bounds: tuple[float, float, float, float], clip: tuple[int, int, int, int]) -> tuple[float, float, float, float]:
    lon_min, lat_min, lon_max, lat_max = bounds
    x0, y1 = mercator(lon_min, lat_min)
    x1, y0 = mercator(lon_max, lat_max)
    width = max(x1 - x0, 1e-9)
    height = max(y1 - y0, 1e-9)
    target_aspect = max(clip[2] / max(clip[3], 1), 1e-9)
    current_aspect = width / height
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    half_w, half_h = width / 2.0, height / 2.0
    if current_aspect < target_aspect:
        half_w = half_h * target_aspect
    else:
        half_h = half_w / target_aspect
    left, right = cx - half_w, cx + half_w
    top, bottom = max(0.0, cy - half_h), min(1.0, cy + half_h)
    out_lon_min, out_lat_max = lonlat_from_mercator(left, top)
    out_lon_max, out_lat_min = lonlat_from_mercator(right, bottom)
    return out_lon_min, out_lat_min, out_lon_max, out_lat_max


def overview_bounds_from_main(bounds: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    lon_min, lat_min, lon_max, lat_max = bounds
    x0, y1 = mercator(lon_min, lat_min)
    x1, y0 = mercator(lon_max, lat_max)
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    width_m = max((LEFT_BLOCK_WIDTH_CM / 100.0) * LOCATION_SCALE_APPROX, LOCATION_MIN_WIDTH_M)
    height_m = width_m * (LOCATION_MAP_HEIGHT_CM / LEFT_BLOCK_WIDTH_CM)
    half_w = (width_m / WORLD_MERCATOR_METRES) / 2.0
    half_h = (height_m / WORLD_MERCATOR_METRES) / 2.0
    left, right = cx - half_w, cx + half_w
    top, bottom = max(0.0, cy - half_h), min(1.0, cy + half_h)
    out_lon_min, out_lat_max = lonlat_from_mercator(left, top)
    out_lon_max, out_lat_min = lonlat_from_mercator(right, bottom)
    return out_lon_min, out_lat_min, out_lon_max, out_lat_max


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
        request = urllib.request.Request(url, headers={"User-Agent": "Analisis-Orografico/3.1.0"})
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
            request = urllib.request.Request(url, headers={"User-Agent": "Analisis-Orografico/3.1.0"})
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
    if provider_key == MAP_BASE_IGN_GRIS and not location:
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
        if provider_key == MAP_BASE_IGN_GRIS and not location:
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


def pil_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\calibrib.ttf" if bold else r"C:\Windows\Fonts\calibri.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    try:
        box = draw.textbbox((0, 0), text, font=font)
        return int(box[2] - box[0]), int(box[3] - box[1])
    except Exception:
        return (len(text) * 9, 16)


def draw_text_halo(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.ImageFont,
    fill: str,
    anchor: str = "la",
    stroke_width: int = 3,
) -> None:
    width = pil_width(stroke_width)
    try:
        draw.text(xy, text, font=font, fill=fill, anchor=anchor, stroke_width=width, stroke_fill="#ffffff")
    except TypeError:
        x, y = xy
        for dx, dy in [(-width, 0), (width, 0), (0, -width), (0, width)]:
            draw.text((x + dx, y + dy), text, font=font, fill="#ffffff")
        draw.text(xy, text, font=font, fill=fill)


def draw_polyline(draw: ImageDraw.ImageDraw, coords: list[tuple[float, float]], fill: str, width: int) -> None:
    if len(coords) < 2:
        return
    line_width = pil_width(width)
    try:
        draw.line(coords, fill=fill, width=line_width, joint="curve")
    except TypeError:
        draw.line(coords, fill=fill, width=line_width)


def draw_dashed_polyline(
    draw: ImageDraw.ImageDraw,
    coords: list[tuple[float, float]],
    fill: str,
    width: int,
    dash: float = 9.0,
    gap: float = 6.0,
) -> None:
    line_width = pil_width(width)
    for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
        length = math.hypot(x2 - x1, y2 - y1)
        if length <= 0:
            continue
        ux, uy = (x2 - x1) / length, (y2 - y1) / length
        pos = 0.0
        while pos < length:
            end = min(pos + dash, length)
            draw.line((x1 + ux * pos, y1 + uy * pos, x1 + ux * end, y1 + uy * end), fill=fill, width=line_width)
            pos += dash + gap


def polygon_coordinate_sequences(geometry: Any) -> list[list[tuple[float, float]]]:
    if geometry is None:
        return []
    if geometry.geom_type == "Polygon":
        return [list(geometry.exterior.coords)]
    if geometry.geom_type == "MultiPolygon":
        return [list(part.exterior.coords) for part in geometry.geoms if part is not None and not part.is_empty]
    if geometry.geom_type == "GeometryCollection":
        result: list[list[tuple[float, float]]] = []
        for part in geometry.geoms:
            result.extend(polygon_coordinate_sequences(part))
        return result
    return []


def line_coordinate_sequences(geometry: Any) -> list[list[tuple[float, float]]]:
    if geometry is None:
        return []
    if geometry.geom_type == "LineString":
        return [list(geometry.coords)]
    if geometry.geom_type == "MultiLineString":
        return [list(part.coords) for part in geometry.geoms]
    if geometry.geom_type == "GeometryCollection":
        result: list[list[tuple[float, float]]] = []
        for part in geometry.geoms:
            result.extend(line_coordinate_sequences(part))
        return result
    return []


def draw_admin_boundaries(draw: ImageDraw.ImageDraw, ccaa: Any, provincias: Any, project: Callable[[float, float], tuple[float, float]]) -> None:
    if provincias is not None:
        try:
            for geom in provincias.geometry:
                for ring in polygon_coordinate_sequences(geom):
                    draw_dashed_polyline(draw, [project(lon, lat) for lon, lat, *_ in ring], "#6d6d6d", 2, dash=14, gap=10)
        except Exception:
            pass
    if ccaa is not None:
        try:
            for geom in ccaa.geometry:
                for ring in polygon_coordinate_sequences(geom):
                    draw_polyline(draw, [project(lon, lat) for lon, lat, *_ in ring], "#4f4f4f", 4)
        except Exception:
            pass


def point_segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 <= 1e-9:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def pk_tick_angle(item: dict[str, Any], roads: list[dict[str, Any]], project: Callable[[float, float], tuple[float, float]]) -> float:
    px, py = project(item["lon"], item["lat"])
    best_distance = float("inf")
    best_angle: float | None = None
    for road in roads:
        for coords in line_coordinate_sequences(road.get("geometry")):
            projected = [project(lon, lat) for lon, lat, *_ in coords]
            for (ax, ay), (bx, by) in zip(projected, projected[1:]):
                distance = point_segment_distance(px, py, ax, ay, bx, by)
                if distance < best_distance:
                    best_distance = distance
                    best_angle = math.degrees(math.atan2(by - ay, bx - ax)) + 90.0
    if best_angle is not None and math.isfinite(best_angle):
        return best_angle
    return 45.0


def make_projector(bounds: tuple[float, float, float, float], clip: tuple[int, int, int, int]) -> Callable[[float, float], tuple[float, float]]:
    lon_min, lat_min, lon_max, lat_max = bounds
    x0, y1 = mercator(lon_min, lat_min)
    x1, y0 = mercator(lon_max, lat_max)
    map_x, map_y, map_w, map_h = clip
    den_x = max(x1 - x0, 1e-12)
    den_y = max(y1 - y0, 1e-12)

    def project(lon: float, lat: float) -> tuple[float, float]:
        mx, my = mercator(lon, lat)
        return map_x + (mx - x0) / den_x * map_w, map_y + (my - y0) / den_y * map_h

    return project


def clip_overlay(canvas: Image.Image, overlay: Image.Image, clip: tuple[int, int, int, int]) -> None:
    x, y, w, h = clip
    canvas.alpha_composite(overlay.crop((x, y, x + w, y + h)), (x, y))


def new_canvas() -> Image.Image:
    return Image.new("RGBA", (MAP_WIDTH, MAP_HEIGHT), "#ffffff")


def draw_main_frame(draw: ImageDraw.ImageDraw) -> None:
    x, y, w, h = MAP_MAIN
    draw.rectangle((x, y, x + w, y + h), fill="#eef1ed", outline="#4d5359", width=3)


def draw_main_outline(draw: ImageDraw.ImageDraw) -> None:
    x, y, w, h = MAP_MAIN
    draw.rectangle((x, y, x + w, y + h), outline="#4d5359", width=3)


def draw_inset_frame(draw: ImageDraw.ImageDraw) -> None:
    x, y, w, h = MAP_INSET
    draw.rectangle((x, y, x + w, y + h), fill="#eef1ed", outline="#4d5359", width=3)


def draw_inset_outline(draw: ImageDraw.ImageDraw) -> None:
    x, y, w, h = MAP_INSET
    draw.rectangle((x, y, x + w, y + h), outline="#4d5359", width=3)


def draw_output_border(draw: ImageDraw.ImageDraw) -> None:
    draw.rectangle((0, 0, MAP_WIDTH - 1, MAP_HEIGHT - 1), outline=MAP_OUTPUT_BORDER_COLOR, width=pil_width(MAP_OUTPUT_BORDER_WIDTH))


def draw_north_arrow(draw: ImageDraw.ImageDraw) -> None:
    map_x, map_y, _map_w, _map_h = MAP_MAIN
    points = [
        (map_x + 76, map_y + 82),
        (map_x + 54, map_y + 148),
        (map_x + 76, map_y + 128),
        (map_x + 98, map_y + 148),
    ]
    draw.polygon(points, fill="#ffffff", outline="#101010")
    draw.line(
        (
            map_x + 76,
            map_y + 82,
            map_x + 54,
            map_y + 148,
            map_x + 76,
            map_y + 128,
            map_x + 98,
            map_y + 148,
            map_x + 76,
            map_y + 82,
        ),
        fill="#101010",
        width=3,
    )


def _scale_km_for_bounds(bounds: tuple[float, float, float, float]) -> float:
    lon_min, lat_min, lon_max, lat_max = bounds
    estimated_km = max(0.2, (lon_max - lon_min) * 111.32 * math.cos(math.radians((lat_min + lat_max) / 2.0)) * 0.28)
    return next((value for value in [100, 50, 20, 10, 5, 2, 1, 0.5, 0.2] if value <= estimated_km), 0.2)


def draw_scale_bar(draw: ImageDraw.ImageDraw, bounds: tuple[float, float, float, float]) -> None:
    loc_x, _loc_y, loc_w, _loc_h = MAP_INSET
    scale_y = MAP_HEIGHT - cm_px(MAP_SCALE_BOTTOM_MARGIN_CM + 0.40 * 1.05)
    scale_km = _scale_km_for_bounds(bounds)
    scale_px = loc_w * 0.78
    scale_x = loc_x + (loc_w - scale_px) / 2.0
    end_tick_h = cm_px(0.20 * 1.05)
    mid_tick_h = cm_px(0.10 * 1.05)
    draw.line((scale_x, scale_y, scale_x + scale_px, scale_y), fill="#111111", width=5)
    draw.line((scale_x, scale_y, scale_x, scale_y - end_tick_h), fill="#111111", width=5)
    draw.line((scale_x + scale_px, scale_y, scale_x + scale_px, scale_y - end_tick_h), fill="#111111", width=5)
    draw.line((scale_x + scale_px / 2.0, scale_y, scale_x + scale_px / 2.0, scale_y - mid_tick_h), fill="#111111", width=4)
    scale_font = pil_font(MAP_SCALE_FONT_SIZE, bold=False)
    try:
        draw.text((scale_x, scale_y - cm_px(MAP_SCALE_TEXT_PAD_CM * 1.05)), "0", font=scale_font, fill="#111111", anchor="mm")
        draw.text((scale_x + scale_px, scale_y - cm_px(MAP_SCALE_TEXT_PAD_CM * 1.05)), f"{scale_km:g} km", font=scale_font, fill="#111111", anchor="mm")
    except TypeError:
        draw.text((scale_x - 4, scale_y - cm_px((MAP_SCALE_TEXT_PAD_CM + 0.10) * 1.05)), "0", font=scale_font, fill="#111111")
        draw.text((scale_x + scale_px - 18, scale_y - cm_px((MAP_SCALE_TEXT_PAD_CM + 0.10) * 1.05)), f"{scale_km:g} km", font=scale_font, fill="#111111")


def wrap_words(text: Any, max_chars: int) -> list[str]:
    words = clean(text).split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        if len(current) + 1 + len(word) <= max_chars:
            current += " " + word
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def draw_left_title(draw: ImageDraw.ImageDraw, title: str, subtitle_lines: list[str]) -> int:
    loc_x, loc_y, _loc_w, loc_h = MAP_INSET
    title_font = pil_font(MAP_TITLE_FONT_SIZE, bold=True)
    subtitle_font = pil_font(MAP_SUBTITLE_FONT_SIZE, bold=False)
    left_text_x = loc_x
    title_y = loc_y + loc_h + cm_px(0.48)
    draw.text((left_text_x, title_y), title, font=title_font, fill=INK)
    subtitle_y = title_y + cm_px(MAP_TITLE_SUBTITLE_GAP_CM)
    subtitle_line_step = cm_px(MAP_SUBTITLE_LINE_STEP_CM)
    for line_index, line in enumerate(subtitle_lines):
        draw.text((left_text_x, subtitle_y + line_index * subtitle_line_step), line, font=subtitle_font, fill=MUTED)
    return subtitle_y + len(subtitle_lines) * subtitle_line_step + cm_px(MAP_LEGEND_Y_OFFSET_CM)


def draw_legend_rows(
    draw: ImageDraw.ImageDraw,
    start_y: int,
    rows: list[tuple[str, str, str]],
) -> None:
    if not rows:
        return
    loc_x, _loc_y, loc_w, _loc_h = MAP_INSET
    scale_y = MAP_HEIGHT - cm_px(MAP_SCALE_BOTTOM_MARGIN_CM + 0.40 * 1.05)
    scale_label_top = scale_y - cm_px(MAP_SCALE_TEXT_PAD_CM * 1.05) - MAP_SCALE_FONT_SIZE
    font_size = MAP_LEGEND_FONT_SIZE
    line_step = MAP_LEGEND_LINE_STEP_PX
    row_min = MAP_LEGEND_ROW_MIN_PX
    font = pil_font(font_size, bold=False)
    prepared = [(label, color, style, wrap_words(label, MAP_LEGEND_WRAP_CHARS)) for label, color, style in rows]
    height = sum(max(row_min, line_step * len(lines) + 34) for _label, _color, _style, lines in prepared)
    if start_y + height > scale_label_top - MAP_LEGEND_SCALE_MIN_GAP_PX:
        font_size = MAP_LEGEND_FALLBACK_FONT_SIZE
        line_step = MAP_LEGEND_FALLBACK_LINE_STEP_PX
        row_min = MAP_LEGEND_FALLBACK_ROW_MIN_PX
        font = pil_font(font_size, bold=False)
    y = start_y
    for label, color, style, lines in prepared:
        if style == "heading":
            heading_font = pil_font(font_size, bold=True)
            draw.text((loc_x + 34, y - 18), clean(label), font=heading_font, fill=INK)
            y += max(MAP_LEGEND_HEADING_STEP_PX, line_step + 24)
            continue
        if style == "line":
            draw.rectangle((loc_x + 34, y - 22, loc_x + 100, y + 6), fill=color, outline="#7f1d1d", width=3)
        elif style == "slope":
            draw.rectangle((loc_x + 34, y - 28, loc_x + 100, y + 12), fill=color, outline="#ffffff", width=2)
        else:
            draw.ellipse((loc_x + 44, y - 24, loc_x + 84, y + 16), fill=color, outline="#ffffff", width=2)
        for line_index, line in enumerate(lines):
            try:
                draw.text((loc_x + min(132, loc_w * 0.30), y - 6 + line_index * line_step), line, font=font, fill="#263544", anchor="lm")
            except TypeError:
                draw.text((loc_x + 132, y - 26 + line_index * line_step), line, font=font, fill="#263544")
        y += max(row_min, line_step * len(lines) + 34)


def save_png_rgb(canvas: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(path, "PNG", optimize=True, dpi=(MAP_DPI, MAP_DPI))


def save_pdf_rgb(canvas: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(path, "PDF", resolution=MAP_DPI)


def map_metadata(mapa_base: str = DEFAULT_MAP_BASE) -> dict[str, Any]:
    provider = tile_provider(mapa_base)
    return {
        "ancho_px": MAP_WIDTH,
        "alto_px": MAP_HEIGHT,
        "mode": "RGB",
        "dpi": MAP_DPI,
        "compositor_usado": "PIL_CARTOGRAFICO",
        "map_main_px": MAP_MAIN,
        "map_inset_px": MAP_INSET,
        "tile_provider": provider["nombre"],
        "tile_cache": str(TILE_CACHE),
    }
