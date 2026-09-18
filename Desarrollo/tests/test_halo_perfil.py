from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from shapely.geometry import LineString


ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(ROOT))

from src.perfiles import calcular_halo_perfil, generar_perfil  # noqa: E402
from src.tramo import TramoExtraido  # noqa: E402


def _tramo(pk_inicio: float, pk_fin: float) -> TramoExtraido:
    start_m = pk_inicio * 1000.0
    end_m = pk_fin * 1000.0
    return TramoExtraido(
        carretera="A-1",
        sentido="creciente",
        pk_inicio_usuario=pk_inicio,
        pk_fin_usuario=pk_fin,
        pk_inicio_recorrido=pk_inicio,
        pk_fin_recorrido=pk_fin,
        pk_min=pk_inicio,
        pk_max=pk_fin,
        longitud_m=end_m - start_m,
        geometry=LineString([(start_m, 0), (end_m, 0)]),
        crs="EPSG:25830",
        advertencias=[],
        metadatos={},
    )


def _pks() -> pd.DataFrame:
    pk = np.linspace(0.0, 30.0, 3001)
    # Curvatura suave: los extremos SG sin contexto y los interiores no son equivalentes.
    z = 0.01 * pk**3 + 4.0 * np.sin(pk * 1.7)
    return pd.DataFrame({"pk": pk, "z": z})


class ProfileCalculationHaloTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pks = _pks()
        self.pk_cols = {"pk": "pk", "z": "z"}
        self.common = dict(
            raster_path=None,
            pks=self.pks,
            pk_cols=self.pk_cols,
            intervalo_m=50.0,
            smoothing=4.0,
            suavizado_pendientes=4.0,
        )

    def _halo(self, tramo: TramoExtraido, **kwargs: object) -> int:
        return int(
            calcular_halo_perfil(
                tramo.longitud_m,
                50.0,
                float(kwargs.get("smoothing", 4.0)),
                str(kwargs.get("suavizado_modo", "simple")),
                kwargs.get("sg_window_puntos"),
                kwargs.get("sg_polyorder"),
                float(kwargs.get("suavizado_pendientes", 4.0)),
                str(kwargs.get("suavizado_pendientes_modo", "simple")),
                kwargs.get("sg_pendientes_window_puntos"),
                kwargs.get("sg_pendientes_polyorder"),
            )["halo_puntos"]
        )

    def _profile(self, tramo: TramoExtraido, tramo_calculo: TramoExtraido | None = None, **kwargs: object):
        options = {**self.common, **kwargs}
        halo = self._halo(tramo, **options)
        return generar_perfil(tramo, tramo_calculo=tramo_calculo, halo_puntos=halo, **options)

    def test_context_on_both_sides_changes_only_the_boundary_solution(self) -> None:
        tramo = _tramo(10.0, 15.0)
        halo = self._halo(tramo)
        with_context, meta, _ = self._profile(_tramo(10.0, 15.0), _tramo(10.0 - halo * 0.05, 15.0 + halo * 0.05))
        without_context, _, _ = self._profile(tramo)
        self.assertEqual(meta["contexto_calculo"]["muestras_contexto_inicio"], halo)
        self.assertEqual(meta["contexto_calculo"]["muestras_contexto_fin"], halo)
        self.assertNotAlmostEqual(
            float(with_context.iloc[0]["pendiente_suavizada_pct"]),
            float(without_context.iloc[0]["pendiente_suavizada_pct"]),
            places=6,
        )
        for row in (0, -1):
            pk = float(with_context.iloc[row]["pk"])
            expected_slope = (0.03 * pk**2 + 6.8 * np.cos(pk * 1.7)) / 10.0
            with_error = abs(float(with_context.iloc[row]["pendiente_suavizada_pct"]) - expected_slope)
            without_error = abs(float(without_context.iloc[row]["pendiente_suavizada_pct"]) - expected_slope)
            self.assertLess(with_error, without_error)
        middle = len(with_context) // 2
        self.assertAlmostEqual(
            float(with_context.iloc[middle]["pendiente_suavizada_pct"]),
            float(without_context.iloc[middle]["pendiente_suavizada_pct"]),
            places=2,
        )

    def test_halo_degrades_naturally_at_each_road_end_and_full_road(self) -> None:
        for requested, calculation, expected_start, expected_end in [
            (_tramo(0.0, 5.0), _tramo(0.0, 5.65), 0, 13),
            (_tramo(25.0, 30.0), _tramo(24.35, 30.0), 13, 0),
            (_tramo(0.0, 30.0), _tramo(0.0, 30.0), 0, 0),
        ]:
            profile, meta, _ = self._profile(requested, calculation)
            context = meta["contexto_calculo"]
            self.assertEqual(context["muestras_contexto_inicio"], expected_start)
            self.assertEqual(context["muestras_contexto_fin"], expected_end)
            self.assertEqual(float(profile.iloc[0]["pk"]), requested.pk_inicio_recorrido)
            self.assertEqual(float(profile.iloc[-1]["pk"]), requested.pk_fin_recorrido)

    def test_visible_mesh_and_scope_remain_exactly_requested(self) -> None:
        tramo = _tramo(10.0, 15.03)
        halo = self._halo(tramo)
        profile, _meta, _ = self._profile(tramo, _tramo(10.0 - halo * 0.05, 15.03 + halo * 0.05))
        expected_distances = np.arange(0.0, 5030.0 + 50.0, 50.0)
        expected_distances[-1] = 5030.0
        np.testing.assert_allclose(profile["distancia_m"].to_numpy(), expected_distances)
        np.testing.assert_allclose(profile["x"].to_numpy(), 10000.0 + expected_distances)
        self.assertEqual(float(profile.iloc[0]["pk"]), 10.0)
        self.assertEqual(float(profile.iloc[-1]["pk"]), 15.03)

    def test_halo_formula_uses_effective_simple_and_advanced_windows(self) -> None:
        tramo = _tramo(10.0, 15.0)
        _profile, simple_meta, _ = self._profile(tramo, _tramo(9.35, 15.65))
        self.assertEqual(simple_meta["contexto_calculo"]["halo_puntos_formula"], 13)

        _profile, advanced_meta, _ = self._profile(
            tramo,
            _tramo(9.55, 15.45),
            suavizado_modo="avanzado",
            sg_window_puntos=11,
            sg_polyorder=2,
            suavizado_pendientes_modo="avanzado",
            sg_pendientes_window_puntos=7,
            sg_pendientes_polyorder=2,
        )
        self.assertEqual(advanced_meta["suavizado_elevaciones"]["sg_window_puntos_aplicada"], 11)
        self.assertEqual(advanced_meta["suavizado_pendientes"]["sg_window_puntos_aplicada"], 7)
        self.assertEqual(advanced_meta["contexto_calculo"]["halo_puntos_formula"], 9)


if __name__ == "__main__":
    unittest.main()
