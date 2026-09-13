from __future__ import annotations

import json
import math
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


APP_ROOT = Path(__file__).resolve().parents[1]
DEVELOPMENT_ROOT = APP_ROOT.parent


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data


def load_config() -> dict[str, Any]:
    config = read_yaml(DEVELOPMENT_ROOT / "config" / "config.yaml")
    styles = read_yaml(DEVELOPMENT_ROOT / "config" / "estilos.yaml")
    config["estilos"] = styles
    return config


def resolve_tool_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (DEVELOPMENT_ROOT / path).resolve()


def resolve_data_path(value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (DEVELOPMENT_ROOT / path).resolve()


def ensure_dir(path: str | Path) -> Path:
    resolved = Path(path)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def json_dump(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2, default=str)


def now_slug() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def slugify(value: Any) -> str:
    text = str(value or "").strip()
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("._")
    return text or "sin_nombre"


def first_existing(row: Any, candidates: list[str], default: Any = None) -> Any:
    for candidate in candidates:
        try:
            value = row.get(candidate)
        except AttributeError:
            value = row[candidate] if candidate in row else None
        if value is not None and not (isinstance(value, float) and math.isnan(value)):
            return value
    return default


def choose_column(columns: list[str], candidates: list[str]) -> str | None:
    lookup = {str(col).lower(): str(col) for col in columns}
    for candidate in candidates:
        if candidate in columns:
            return candidate
        found = lookup.get(candidate.lower())
        if found:
            return found
    return None


def as_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        if isinstance(value, str):
            value = value.strip().replace(",", ".")
            if not value:
                return default
        result = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(result):
        return default
    return result


def pk_to_m(pk: float) -> float:
    return float(pk) * 1000.0


def format_pk(pk: Any) -> str:
    value = as_float(pk, 0.0) or 0.0
    sign = "-" if value < 0 else ""
    value = abs(value)
    km = int(math.floor(value))
    metres = int(round((value - km) * 1000))
    if metres >= 1000:
        km += 1
        metres -= 1000
    return f"{sign}{km}+{metres:03d}"


def parse_interval(value: Any) -> float | None:
    if value in (None, "", "auto"):
        return None
    return as_float(value)


def method_notes() -> list[str]:
    return [
        "Las cotas proceden de MDT o de cotas puntuales de PK cuando el MDT no esta disponible; no equivalen a una rasante topografica levantada.",
        "En tuneles, viaductos, pasos superiores o zonas con fuerte modificacion artificial del terreno, la cota puede no representar exactamente la plataforma.",
        "La pendiente representada es una pendiente media por intervalo cartografico.",
        "El suavizado reduce ruido del MDT, pero puede atenuar cambios locales bruscos.",
        "El intervalo de muestreo recomendado debe ser al menos cuatro veces el tamano de pixel del MDT utilizado.",
    ]


def warning_text(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items if item)
