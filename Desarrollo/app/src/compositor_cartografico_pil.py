from __future__ import annotations

import math
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFont

from .basemaps import DEFAULT_MAP_BASE, TILE_CACHE, WORLD_MERCATOR_METRES, lonlat_from_mercator, mercator, tile_provider

MAP_DPI = 600

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

def cm_px(value: float) -> int:
    return int(round(value * MAP_PX_PER_CM))


def pil_width(value: float | int) -> int:
    return max(1, int(round(float(value))))


def clean(value: Any) -> str:
    return str(value or "").strip()






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
        elif style == "divided_line":
            left, top, right, bottom = loc_x + 34, y - 22, loc_x + 100, y + 6
            middle = (left + right) // 2
            draw.rectangle((left, top, middle, bottom), fill="#f4a3a8")
            draw.rectangle((middle, top, right, bottom), fill="#df7f87")
            draw.rectangle((left, top, right, bottom), outline="#7f1d1d", width=3)
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
