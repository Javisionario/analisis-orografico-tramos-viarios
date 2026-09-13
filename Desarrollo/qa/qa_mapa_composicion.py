from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(ROOT))

from src.compositor_cartografico_pil import MAP_DPI, MAP_HEIGHT, MAP_INSET, MAP_MAIN, MAP_WIDTH  # noqa: E402


FRAME_RGB = (77, 83, 89)


def _close_rgb(a: tuple[int, int, int], b: tuple[int, int, int], tolerance: int = 18) -> bool:
    return all(abs(int(a[i]) - int(b[i])) <= tolerance for i in range(3))


def _frame_pixels(rect: tuple[int, int, int, int]) -> list[tuple[int, int]]:
    x, y, w, h = rect
    return [
        (x + 1, y + 1),
        (x + w // 2, y + 1),
        (x + w - 1, y + 1),
        (x + 1, y + h // 2),
        (x + w - 1, y + h // 2),
        (x + 1, y + h - 1),
        (x + w // 2, y + h - 1),
        (x + w - 1, y + h - 1),
    ]


def _frame_ok(image: Image.Image, rect: tuple[int, int, int, int]) -> bool:
    rgb = image.convert("RGB")
    hits = 0
    for point in _frame_pixels(rect):
        if _close_rgb(rgb.getpixel(point), FRAME_RGB):
            hits += 1
    return hits >= 6


def main() -> int:
    parser = argparse.ArgumentParser(description="QA de composición de mapas PIL.")
    parser.add_argument("png", type=Path)
    args = parser.parse_args()
    image = Image.open(args.png)
    dpi = image.info.get("dpi")
    dpi_values = tuple(float(v) for v in dpi) if isinstance(dpi, tuple) else (0.0, 0.0)
    checks = {
        "path": str(args.png),
        "width": image.size[0],
        "height": image.size[1],
        "mode": image.mode,
        "dpi": dpi_values,
        "size_ok": image.size == (MAP_WIDTH, MAP_HEIGHT),
        "mode_ok": image.mode == "RGB",
        "dpi_ok": all(abs(value - MAP_DPI) <= 2 for value in dpi_values),
        "no_alpha": "A" not in image.getbands(),
        "main_frame_ok": _frame_ok(image, MAP_MAIN),
        "inset_frame_ok": _frame_ok(image, MAP_INSET),
        "expected": {
            "width": MAP_WIDTH,
            "height": MAP_HEIGHT,
            "mode": "RGB",
            "dpi": MAP_DPI,
            "map_main_px": MAP_MAIN,
            "map_inset_px": MAP_INSET,
        },
    }
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    required = ["size_ok", "mode_ok", "dpi_ok", "no_alpha", "main_frame_ok", "inset_frame_ok"]
    return 0 if all(checks[item] for item in required) else 1


if __name__ == "__main__":
    raise SystemExit(main())
