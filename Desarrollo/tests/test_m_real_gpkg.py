from __future__ import annotations

"""Regression checks against the shipped calibrated GeoPackage, not a mock."""

import sys
import unittest
from pathlib import Path

import numpy as np
import geopandas as gpd
from shapely.geometry import LineString
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(ROOT))

from src.io_datos import diagnostico_capas, load_admin, load_lineas, load_pks, read_layer_bbox, viario_path, line_layer  # noqa: E402
from src.utils import load_config  # noqa: E402
from src.visor_red import localizar_pk, punto_a_pk  # noqa: E402
from src.tramo import extraer_tramo  # noqa: E402


class RealMeasuredGpkgTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = load_config()
        if not viario_path(cls.config).exists():
            raise unittest.SkipTest("No está disponible el GeoPackage calibrado del proyecto.")

    def test_a1_pk30_uses_original_m_and_roundtrips_to_pk_layer(self) -> None:
        lineas, cols, _notes = load_lineas(self.config, "A-1")
        pks, pk_cols, _notes = load_pks(self.config, "A-1")
        located = localizar_pk(lineas, cols, "A-1", 30.0)
        pk_field = pk_cols["pk"]
        candidates = pks.loc[(pks[pk_field].astype(float) - 30.0).abs() < 1e-9]
        if "TIPO" in candidates.columns:
            candidates = candidates.loc[candidates["TIPO"].astype(str) == "0"]
        pk_point = candidates.iloc[0].geometry
        # The real M location is 1.77 m from the supplied PK; global XY
        # proportionality put this case about 675 m away.
        self.assertLess(located.snapped.distance(pk_point), 3.0)
        candidates = punto_a_pk(lineas, cols, pk_point, 20.0)
        self.assertTrue(any(abs(item.pk - 30.0) < 0.001 for item in candidates))

    def test_bbox_loader_keeps_fid_bound_measured_coordinates(self) -> None:
        lineas, cols, _notes = load_lineas(self.config, "A-1")
        point = localizar_pk(lineas, cols, "A-1", 30.0).snapped
        bbox = (point.x - 100, point.y - 100, point.x + 100, point.y + 100)
        subset, _notes = read_layer_bbox(viario_path(self.config), line_layer(self.config), bbox)
        self.assertGreater(len(subset), 0)
        self.assertTrue(any(bool(parts) for parts in subset["__m_parts"]))

    def test_recovered_m_suppresses_pyogrio_loss_warning(self) -> None:
        _lineas, _cols, notes = load_lineas(self.config, "A-1")
        self.assertFalse(any("Measured" in note or "(M)" in note for note in notes))

    def test_non_measured_layers_do_not_report_linear_referencing_fallback(self) -> None:
        _pks, _cols, pk_notes = load_pks(self.config, "A-1")
        _ccaa, _provincias, admin_notes = load_admin(self.config)
        self.assertFalse(any("fallback explícito" in note for note in pk_notes + admin_notes))

    def test_diagnostic_does_not_presume_fallback_for_a_recovered_layer(self) -> None:
        # Keep this contract test small: the expensive data loading is covered
        # above; only the diagnostic's final interpretation is under test.
        with patch("src.io_datos.list_layers", return_value=([{"name": "VíasDGT_Calibrada", "geometry_type": "Measured LineString"}], ["Measured geometry converted"])), \
             patch("src.io_datos.load_lineas", return_value=(gpd.GeoDataFrame({"__m_parts": [[[(0, 0, 0), (1, 0, 1)]]]}, geometry=[LineString([(0, 0), (1, 0)])], crs="EPSG:25830"), {"carretera": "road"}, [])), \
             patch("src.io_datos.load_pks", return_value=(gpd.GeoDataFrame(geometry=[], crs="EPSG:25830"), {}, [])):
            diagnostic = diagnostico_capas(self.config)
        self.assertFalse(any("fallback" in note.lower() or "Measured" in note for note in diagnostic["advertencias"]))

    def test_pk2023_sample_has_low_error_against_real_m(self) -> None:
        """A reproducible, unambiguous PK_2023 sample across four roads."""
        errors_m: list[float] = []
        for road in ("A-1", "M-11", "N-110", "N-320"):
            lineas, cols, _notes = load_lineas(self.config, road)
            pks, pk_cols, _notes = load_pks(self.config, road)
            if "TIPO" in pks.columns:
                pks = pks.loc[pks["TIPO"].astype(str) == "0"]
            if pks.empty:
                continue
            sample = pks.iloc[np.linspace(0, len(pks) - 1, min(8, len(pks)), dtype=int)]
            for _fid, item in sample.iterrows():
                value_m = float(item.get("VALORM", item[pk_cols["pk"]] * 1000.0))
                matched = punto_a_pk(lineas, cols, item.geometry, 30.0)
                if matched:
                    errors_m.append(min(abs(candidate.pk * 1000.0 - value_m) for candidate in matched))
        self.assertGreaterEqual(len(errors_m), 24)
        self.assertLessEqual(float(np.percentile(errors_m, 95)), 5.0)

    def test_a1_29_to_31_map_geometry_uses_real_m_endpoints_and_pk30(self) -> None:
        lineas, cols, _notes = load_lineas(self.config, "A-1")
        tramo = extraer_tramo(lineas, cols, "A-1", 29.0, 31.0, "creciente")
        start = localizar_pk(lineas, cols, "A-1", 29.0).snapped
        middle = localizar_pk(lineas, cols, "A-1", 30.0).snapped
        end = localizar_pk(lineas, cols, "A-1", 31.0).snapped
        coords = list(tramo.geometry.geoms[0].coords) if hasattr(tramo.geometry, "geoms") else list(tramo.geometry.coords)
        self.assertLess(np.hypot(coords[0][0] - start.x, coords[0][1] - start.y), 0.01)
        self.assertLess(np.hypot(coords[-1][0] - end.x, coords[-1][1] - end.y), 0.01)
        self.assertLess(tramo.geometry.distance(middle), 0.01)


if __name__ == "__main__":
    unittest.main()
