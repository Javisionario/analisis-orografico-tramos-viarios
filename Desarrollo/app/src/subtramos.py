from __future__ import annotations

"""Semantic validation and diagnostics for logical subsegments."""

from typing import Any

from .io_datos import normalize_road_name


TOLERANCIA_KM = 0.002


def analizar_subtramos(tramos: list[dict[str, Any]], tolerancia_km: float = TOLERANCIA_KM) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for index, raw in enumerate(tramos, 1):
        try:
            inicio, fin = float(raw.get("pk_inicio")), float(raw.get("pk_fin"))
        except (TypeError, ValueError):
            return {"valido": False, "motivo": "Los subtramos deben tener PK válidos.", "huecos": [], "solapes": []}
        items.append({"indice": index, "carretera": str(raw.get("carretera") or "").strip(), "normalizado": normalize_road_name(raw.get("carretera")), "sentido": str(raw.get("sentido") or "creciente").strip().lower(), "pk_inicio": inicio, "pk_fin": fin})
    if len(items) < 2:
        return {"valido": False, "motivo": "Se requieren al menos dos subtramos.", "huecos": [], "solapes": []}
    roads = {item["normalizado"] for item in items}
    directions = {item["sentido"] for item in items}
    if not roads or "" in roads or len(roads) != 1 or len(directions) != 1:
        return {"valido": False, "motivo": "Los subtramos deben pertenecer a la misma carretera y utilizar el mismo sentido.", "huecos": [], "solapes": []}
    direction = next(iter(directions))
    gaps: list[dict[str, Any]] = []
    overlaps: list[dict[str, Any]] = []
    # Preserve ``items`` in user order for profiles, IDs and metadata. This
    # copy is deliberately canonical and sorted only for topology diagnosis.
    diagnostic = sorted(
        ({**item, "low": min(item["pk_inicio"], item["pk_fin"]), "high": max(item["pk_inicio"], item["pk_fin"])} for item in items),
        key=lambda item: (item["low"], item["high"], item["indice"]),
    )
    for previous, current in zip(diagnostic, diagnostic[1:]):
        difference = current["low"] - previous["high"]
        detail = {"entre": [previous["indice"], current["indice"]], "km": round(abs(difference), 6), "desde": previous["high"], "hasta": current["low"]}
        if difference > tolerancia_km:
            gaps.append(detail)
        elif difference < -tolerancia_km:
            overlaps.append(detail)
    minimum = min(min(item["pk_inicio"], item["pk_fin"]) for item in items)
    maximum = max(max(item["pk_inicio"], item["pk_fin"]) for item in items)
    return {"valido": True, "motivo": "", "carretera": items[0]["carretera"], "sentido": direction, "numero_subtramos": len(items), "pk_global_inicio": maximum if direction == "decreciente" else minimum, "pk_global_fin": minimum if direction == "decreciente" else maximum, "subtramos": items, "huecos": gaps, "solapes": overlaps, "tolerancia_km": tolerancia_km}
