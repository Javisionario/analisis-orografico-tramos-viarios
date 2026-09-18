from __future__ import annotations

import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from PIL import Image


ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(ROOT))

from src import compositor_cartografico_pil as compositor  # noqa: E402


class _Response:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.data


def _png(width: int, height: int) -> bytes:
    data = BytesIO()
    Image.new("RGB", (width, height), "#d9d9d9").save(data, "PNG")
    return data.getvalue()


class IgnWmsBasemapTests(unittest.TestCase):
    bounds = (-1.8978952214, 42.8886548708, -1.8260744523, 42.9401456285)
    clip = (11, 13, 2799, 2740)

    def setUp(self) -> None:
        compositor.BASEMAP_RASTER_CACHE.clear()

    def test_wms_request_uses_main_bbox_clip_and_isolated_cache_key(self) -> None:
        image = _png(self.clip[2], self.clip[3])
        with patch.object(compositor, "TILE_CACHE", Path("wms-cache-test")), patch.object(Path, "mkdir"), patch.object(Path, "write_bytes"), patch(
            "src.compositor_cartografico_pil.urllib.request.urlopen", return_value=_Response(image)
        ) as urlopen:
            data = compositor.ign_wms_bytes(self.bounds, self.clip[2], self.clip[3])
            cache = compositor.ign_wms_cache_path(self.bounds, self.clip[2], self.clip[3])

        self.assertEqual(data, image)
        self.assertTrue(cache.name.startswith(f"ign_wms_{compositor.IGN_WMS_LAYER}_{compositor.IGN_WMS_DPI}_"))
        request = urlopen.call_args.args[0]
        self.assertEqual(urlsplit(request.full_url).path, "/wms-inspire/ign-base")
        params = parse_qs(urlsplit(request.full_url).query, keep_blank_values=True)
        self.assertEqual(params["SERVICE"], ["WMS"])
        self.assertEqual(params["REQUEST"], ["GetMap"])
        self.assertEqual(params["LAYERS"], [compositor.IGN_WMS_LAYER])
        self.assertEqual(params["CRS"], ["EPSG:3857"])
        self.assertEqual(params["WIDTH"], [str(self.clip[2])])
        self.assertEqual(params["HEIGHT"], [str(self.clip[3])])
        self.assertEqual(params["FORMAT"], ["image/png"])
        self.assertEqual(params["TRANSPARENT"], ["false"])
        self.assertEqual(params["FORMAT_OPTIONS"], [f"dpi:{compositor.IGN_WMS_DPI}"])
        self.assertEqual(
            params["BBOX"],
            [",".join(f"{value:.12f}" for value in compositor.ign_wms_bbox(self.bounds))],
        )

    def test_main_ign_prefers_wms_without_calling_tms(self) -> None:
        canvas = Image.new("RGBA", (4000, 3000))
        config: dict[str, object] = {}
        with patch("src.compositor_cartografico_pil.ign_wms_basemap_raster", return_value=True) as wms, patch(
            "src.compositor_cartografico_pil.basemap_raster", return_value=True
        ) as tms:
            ok = compositor.render_report_basemap(self.bounds, canvas, self.clip, config, location=False, mapa_base="ign_gris")
        self.assertTrue(ok)
        wms.assert_called_once()
        tms.assert_not_called()
        self.assertEqual(config["metodo"], "wms")
        self.assertFalse(config["fallback_tms_usado"])
        self.assertEqual(config["wms"]["bbox_3857"], list(compositor.ign_wms_bbox(self.bounds)))  # type: ignore[index]

    def test_main_ign_falls_back_to_existing_tms_when_wms_fails(self) -> None:
        canvas = Image.new("RGBA", (4000, 3000))
        config: dict[str, object] = {}
        with patch("src.compositor_cartografico_pil.ign_wms_basemap_raster", return_value=False), patch(
            "src.compositor_cartografico_pil.basemap_raster", return_value=True
        ) as tms:
            ok = compositor.render_report_basemap(self.bounds, canvas, self.clip, config, location=False, mapa_base="ign_gris")
        self.assertTrue(ok)
        tms.assert_called_once()
        self.assertEqual(config["metodo"], "tms_fallback")
        self.assertTrue(config["fallback_tms_usado"])

    def test_location_ign_prefers_wms_without_calling_tms(self) -> None:
        canvas = Image.new("RGBA", (4000, 3000))
        config: dict[str, object] = {}
        with patch("src.compositor_cartografico_pil.ign_wms_basemap_raster", return_value=True) as wms, patch(
            "src.compositor_cartografico_pil.basemap_raster", return_value=True
        ) as tms:
            ok = compositor.render_report_basemap(self.bounds, canvas, self.clip, config, location=True, mapa_base="ign_gris")
        self.assertTrue(ok)
        wms.assert_called_once_with(
            self.bounds,
            canvas,
            self.clip,
            compositor.LOC_BASEMAP_BRIGHTNESS,
            compositor.LOC_BASEMAP_SATURATION,
            compositor.LOC_BASEMAP_GAMMA,
        )
        tms.assert_not_called()
        self.assertEqual(config["metodo"], "wms")
        self.assertFalse(config["fallback_tms_usado"])
        self.assertEqual(config["wms"]["width"], self.clip[2])  # type: ignore[index]
        self.assertEqual(config["wms"]["height"], self.clip[3])  # type: ignore[index]

    def test_location_ign_falls_back_to_existing_tms_when_wms_fails(self) -> None:
        canvas = Image.new("RGBA", (4000, 3000))
        config: dict[str, object] = {}
        with patch("src.compositor_cartografico_pil.ign_wms_basemap_raster", return_value=False), patch(
            "src.compositor_cartografico_pil.basemap_raster", return_value=True
        ) as tms:
            ok = compositor.render_report_basemap(self.bounds, canvas, self.clip, config, location=True, mapa_base="ign_gris")
        self.assertTrue(ok)
        tms.assert_called_once()
        self.assertEqual(config["metodo"], "tms_fallback")
        self.assertTrue(config["fallback_tms_usado"])


if __name__ == "__main__":
    unittest.main()
