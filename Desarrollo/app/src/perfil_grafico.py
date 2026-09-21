from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.ticker import AutoMinorLocator, FixedLocator, FuncFormatter, MaxNLocator

from .estilos import resolver_fuente_mpl
from .perfiles import _elevation_axis
from .referenciacion_lineal import distance_at_m
from .tramo import TramoExtraido
from .utils import format_pk


PROFILE_ANOMALY_COLOR = "#c2b206"
PROFILE_DIVISION_FILL_PALETTE = ("#9bc8a0", "#4f8f63")


def _nice_pk_ticks(start: float, end: float, target: int = 6) -> list[float]:
    lo, hi = min(float(start), float(end)), max(float(start), float(end))
    span = hi - lo
    if span <= 0:
        return [float(start)]
    candidates = [0.5, 1, 2, 5, 10, 20, 25, 50, 100]
    step = min(candidates, key=lambda value: abs((span / value) - target))
    for candidate in candidates:
        approx = span / candidate
        if 5 <= approx <= 8:
            step = candidate
            break
    first = np.ceil(lo / step) * step
    ticks: list[float] = []
    value = first
    while value <= hi + step * 0.25:
        ticks.append(round(float(value), 6))
        value += step
    return ticks or [lo, hi]


def _slope_color(value: float) -> str:
    if value <= -4.0:
        return "#2879b9"
    if value < -0.35:
        return "#5fa6d3"
    if value <= 0.35:
        return "#8d969b"
    if value < 4.0:
        return "#df6f66"
    return "#b2182b"


def _slope_axis(values: np.ndarray) -> dict[str, Any] | None:
    finite = values[np.isfinite(values)]
    if not len(finite):
        return None
    max_abs = float(np.max(np.abs(finite)))
    if max_abs <= 2.25:
        return {"low": -2.5, "high": 2.5, "ticks": (-2.0, -1.0, 0.0, 1.0, 2.0)}
    if max_abs <= 4.5:
        return {"low": -5.0, "high": 5.0, "ticks": (-4.0, -2.0, 0.0, 2.0, 4.0)}
    low = min(float(np.min(finite)), 0.0)
    high = max(float(np.max(finite)), 0.0)
    if abs(high - low) < 1e-6:
        low -= 1.0
        high += 1.0
    margin = max(0.8, (high - low) * 0.18)
    return {"low": low - margin, "high": high + margin, "ticks": None}


def distance_at_pk(distances: np.ndarray, pk_values: np.ndarray, pk: float) -> float:
    """Interpolate the measured distance↔PK relation without global linearisation."""
    distance_array = np.asarray(distances, dtype=float)
    pk_array = np.asarray(pk_values, dtype=float)
    valid = np.isfinite(distance_array) & np.isfinite(pk_array)
    if not np.any(valid):
        raise ValueError("No hay relación válida entre distancia y PK.")
    pairs = sorted(zip(pk_array[valid], distance_array[valid]), key=lambda item: item[0])
    sorted_pk = np.asarray([item[0] for item in pairs], dtype=float)
    sorted_distance = np.asarray([item[1] for item in pairs], dtype=float)
    target = float(pk)
    if target < sorted_pk[0] - 1e-9 or target > sorted_pk[-1] + 1e-9:
        raise ValueError("El PK está fuera del perfil.")
    return float(np.interp(target, sorted_pk, sorted_distance))


def _distance_for_pk(tramo: TramoExtraido, x: np.ndarray, pk_values: np.ndarray, pk: float) -> float:
    if len(tramo.calibracion_distancia_m) >= 2:
        return distance_at_m(tramo.calibracion_distancia_m, float(pk) * 1000.0)
    return distance_at_pk(x, pk_values, pk)


def division_fill_arrays(x: np.ndarray, z: np.ndarray, start: float, end: float) -> tuple[np.ndarray, np.ndarray]:
    """Return the exact polygon vertices for one physical span of a profile."""
    low, high = sorted((float(start), float(end)))
    if high <= low:
        raise ValueError("La división debe tener una extensión física positiva.")
    interior = (x > low) & (x < high)
    x_part = np.concatenate(([low], x[interior], [high]))
    z_part = np.concatenate(([np.interp(low, x, z)], z[interior], [np.interp(high, x, z)]))
    return x_part, z_part


def exportar_perfil(
    df: pd.DataFrame,
    output_base: Path,
    mostrar_pendiente: bool,
    tramo: TramoExtraido,
    modo_eje_y: str = "cero",
    mostrar_linea_muestreada_elevaciones: bool = False,
    divisiones: list[dict[str, Any]] | None = None,
) -> list[Path]:
    paths = [
        output_base.with_suffix(".png"),
        output_base.with_suffix(".pdf"),
        output_base.with_suffix(".svg"),
    ]
    font_name = resolver_fuente_mpl()
    plt.rcParams.update({
        "font.family": font_name,
        "axes.edgecolor": "#25313a",
        "axes.linewidth": 0.85,
    })
    fig, ax = plt.subplots(figsize=(10.8, 4.6), dpi=240)
    x = df["distancia_m"].to_numpy(dtype=float)
    pk_values = df["pk"].to_numpy(dtype=float)
    z = df["cota_suavizada_m"].to_numpy(dtype=float)
    raw = df["cota_bruta_m"].to_numpy(dtype=float)
    y_axis = _elevation_axis(z, modo_eje_y)
    zmin = float(y_axis["y_min_visual"])

    parts = list(divisiones or [])
    if len(parts) > 1:
        for part in parts:
            start = _distance_for_pk(tramo, x, pk_values, float(part["pk_inicio"]))
            end = _distance_for_pk(tramo, x, pk_values, float(part["pk_fin"]))
            x_part, z_part = division_fill_arrays(x, z, start, end)
            color = PROFILE_DIVISION_FILL_PALETTE[(int(part["indice"]) - 1) % len(PROFILE_DIVISION_FILL_PALETTE)]
            ax.fill_between(x_part, z_part, zmin, color=color, alpha=0.32, linewidth=0)
    else:
        ax.fill_between(x, z, zmin, color=PROFILE_DIVISION_FILL_PALETTE[0], alpha=0.32, linewidth=0)
    ax.plot(x, z, color="#255f3c", linewidth=2.0, zorder=3)
    if mostrar_linea_muestreada_elevaciones:
        ax.plot(x, raw, color="#6f8f77", linewidth=0.7, alpha=0.42, zorder=2)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"{value:g} m"))
    tick_pks = _nice_pk_ticks(float(pk_values[0]), float(pk_values[-1]))
    tick_positions = [_distance_for_pk(tramo, x, pk_values, value) for value in tick_pks]
    ax.set_xticks(tick_positions, [format_pk(value) for value in tick_pks])
    ax.xaxis.set_minor_locator(AutoMinorLocator(2))
    ax.yaxis.set_minor_locator(AutoMinorLocator(2))
    ax.set_xlabel("")
    ax.set_ylabel("")
    ax.grid(True, which="major", color="#9fb0bd", linewidth=0.62, alpha=0.38)
    ax.grid(True, which="minor", color="#d3dce3", linewidth=0.42, alpha=0.42)
    ax.set_facecolor("#fbfcfb")
    fig.patch.set_facecolor("#ffffff")
    ax.set_xlim(float(np.min(x)), float(np.max(x)))
    for label in ax.get_xticklabels():
        label.set_rotation(24)
        label.set_ha("right")
    ax.set_ylim(float(y_axis["y_min_visual"]), float(y_axis["y_max"]))
    ax.set_yticks(np.arange(float(y_axis["y_tick_min"]), float(y_axis["y_tick_max"]) + float(y_axis["y_tick_step"]) * 0.5, float(y_axis["y_tick_step"])))

    fig.text(0.075, 0.965, "Perfil longitudinal", ha="left", va="top", fontsize=14.5, weight="bold", color="#17212b")
    subtitle = f"{tramo.carretera} · {tramo.sentido} · PK {format_pk(tramo.pk_inicio_recorrido)} a {format_pk(tramo.pk_fin_recorrido)}"
    if mostrar_pendiente and "pendiente_representada_pct" in df.columns:
        finite_slope = df["pendiente_representada_pct"].to_numpy(dtype=float)
        finite_slope = finite_slope[np.isfinite(finite_slope)]
        if len(finite_slope):
            mean_abs = float(np.nanmean(np.abs(finite_slope)))
            mean_abs_txt = f"{mean_abs:.1f}".replace(".", ",")
            subtitle = f"{subtitle} · pendiente media abs. {mean_abs_txt} %"
    fig.text(0.075, 0.905, subtitle, ha="left", va="top", fontsize=10.2, color="#526273")

    if mostrar_pendiente:
        ax2 = ax.twinx()
        slope = df["pendiente_representada_pct"].to_numpy(dtype=float)
        anomalies = df["pendiente_anomala"].astype(bool).to_numpy() if "pendiente_anomala" in df.columns else np.zeros(len(df), dtype=bool)
        for idx in range(max(0, len(x) - 1)):
            if not np.all(np.isfinite([x[idx], x[idx + 1], slope[idx], slope[idx + 1]])):
                continue
            anomalous = bool(anomalies[idx] or anomalies[idx + 1])
            color = PROFILE_ANOMALY_COLOR if anomalous else _slope_color(float(np.nanmean([slope[idx], slope[idx + 1]])))
            ax2.plot(
                [x[idx], x[idx + 1]],
                [slope[idx], slope[idx + 1]],
                color=color,
                linewidth=1.35,
                linestyle="-",
                solid_capstyle="butt",
                clip_on=True,
                zorder=4,
            )
        ax2.set_ylabel("")
        ax2.yaxis.set_major_formatter(FuncFormatter(lambda value, _pos: f"{value:.1f} %"))
        slope_axis = _slope_axis(slope)
        if slope_axis:
            ax2.set_ylim(float(slope_axis["low"]), float(slope_axis["high"]))
        ax2.set_xlim(ax.get_xlim())
        if slope_axis and slope_axis["ticks"] is not None:
            ax2.yaxis.set_major_locator(FixedLocator(slope_axis["ticks"]))
        else:
            ax2.yaxis.set_major_locator(MaxNLocator(nbins=6))
        ax2.grid(False)

    legend_items = [Line2D([0], [0], color="#255f3c", linewidth=2.2, label="Elevaciones (m)")]
    if mostrar_pendiente:
        legend_items.append(Line2D([0], [0], color="#66717c", linewidth=1.8, linestyle="-", label="Pendientes (%)"))
    if mostrar_linea_muestreada_elevaciones:
        legend_items.append(Line2D([0], [0], color="#6f8f77", linewidth=1.0, alpha=0.7, label="Elevaciones muestreadas (m)"))
    ax.legend(handles=legend_items, loc="center left", bbox_to_anchor=(1.08, 0.5), frameon=False, fontsize=9.2)
    fig.subplots_adjust(left=0.075, right=0.79, top=0.84, bottom=0.18)
    for path in paths:
        fig.savefig(path, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return paths
