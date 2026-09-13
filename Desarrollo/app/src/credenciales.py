from __future__ import annotations

try:
    import keyring
except ImportError:  # La aplicación conserva el uso manual si keyring no está instalado.
    keyring = None


CARTO_KEYRING_SERVICE = "analisis-orografico-tramos-viarios"
CARTO_KEYRING_USERNAME = "carto_basemaps_api_key"


def obtener_api_key_carto() -> str | None:
    if keyring is None:
        return None
    try:
        value = keyring.get_password(CARTO_KEYRING_SERVICE, CARTO_KEYRING_USERNAME)
    except Exception:
        return None
    if value is None:
        return None
    return str(value).strip() or None


def guardar_api_key_carto(api_key: str) -> bool:
    if keyring is None:
        return False
    value = str(api_key or "").strip()
    if not value:
        return False
    try:
        keyring.set_password(CARTO_KEYRING_SERVICE, CARTO_KEYRING_USERNAME, value)
    except Exception:
        return False
    return True


def eliminar_api_key_carto() -> bool:
    if keyring is None:
        return False
    try:
        keyring.delete_password(CARTO_KEYRING_SERVICE, CARTO_KEYRING_USERNAME)
    except Exception:
        return False
    return True
