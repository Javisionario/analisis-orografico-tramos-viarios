from __future__ import annotations

"""Derivación de divisiones visuales dentro de un tramo real."""

import math
from typing import Any

TOLERANCIA_KM = 0.002
DIVISION_COLORS = ("#f4a3a8", "#df7f87")


class DivisionError(ValueError):
    """Una división de PK no es válida para el tramo solicitado."""


def _number(value: Any, label: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DivisionError(f"{label} debe ser numérico.") from exc
    if not math.isfinite(result):
        raise DivisionError(f"{label} debe ser finito.")
    return result


def normalizar_divisiones(pk_inicio: Any, pk_fin: Any, divisiones_pk: list[Any] | None,
                          sentido: str = "creciente", tolerancia_km: float = TOLERANCIA_KM) -> list[float]:
    """Valida y ordena las divisiones en el sentido del recorrido."""
    inicio, fin = _number(pk_inicio, "PK inicio"), _number(pk_fin, "PK fin")
    low, high = min(inicio, fin), max(inicio, fin)
    if high - low <= tolerancia_km:
        raise DivisionError("El tramo debe tener una longitud superior a la tolerancia.")
    values = [_number(value, "Cada división") for value in (divisiones_pk or [])]
    for value in values:
        if value <= low + tolerancia_km or value >= high - tolerancia_km:
            raise DivisionError("Cada división debe quedar estrictamente dentro del tramo.")
    ordered = sorted(values)
    if any(current - previous <= tolerancia_km for previous, current in zip(ordered, ordered[1:])):
        raise DivisionError("No puede haber divisiones duplicadas o separadas menos de 2 m.")
    return list(reversed(ordered)) if str(sentido or "").strip().lower() == "decreciente" else ordered


def derivar_subtramos(pk_inicio: Any, pk_fin: Any, divisiones_pk: list[Any] | None,
                      sentido: str = "creciente", tolerancia_km: float = TOLERANCIA_KM) -> list[dict[str, Any]]:
    """Devuelve partes D01… contiguas; no son scopes ni perfiles nuevos."""
    inicio, fin = _number(pk_inicio, "PK inicio"), _number(pk_fin, "PK fin")
    direction = str(sentido or "creciente").strip().lower()
    start, end = (max(inicio, fin), min(inicio, fin)) if direction == "decreciente" else (min(inicio, fin), max(inicio, fin))
    divisions = normalizar_divisiones(start, end, divisiones_pk, direction, tolerancia_km)
    points = [start, *divisions, end]
    return [
        {"id": f"D{index:02d}", "indice": index, "pk_inicio": float(left), "pk_fin": float(right),
         "color": DIVISION_COLORS[(index - 1) % len(DIVISION_COLORS)]}
        for index, (left, right) in enumerate(zip(points, points[1:]), 1)
    ]
