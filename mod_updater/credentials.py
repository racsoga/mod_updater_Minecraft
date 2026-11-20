"""API key de CurseForge en el Administrador de credenciales de Windows (keyring).

- Nunca se escribe en archivos de la app ni en logs.
- En pantalla solo se muestran los últimos 4 caracteres (`hint`).
- En desarrollo, si no hay key en keyring, se usa `CF_API_KEY` del `.env`.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

from .config import PROJECT_ROOT

SERVICE = "mod_updater"
ACCOUNT = "curseforge_api_key"

try:  # keyring puede no estar disponible en algún entorno raro
    import keyring
    from keyring.errors import KeyringError
except ImportError:  # pragma: no cover
    keyring = None
    KeyringError = Exception


def get_key() -> tuple[str | None, str | None]:
    """Devuelve (key, origen) con origen "keyring", "env" o None."""
    if keyring is not None:
        try:
            k = keyring.get_password(SERVICE, ACCOUNT)
        except KeyringError:
            k = None
        if k:
            return k, "keyring"
    load_dotenv(PROJECT_ROOT / ".env")
    k = os.environ.get("CF_API_KEY") or None
    return (k, "env") if k else (None, None)


def set_key(key: str) -> None:
    if keyring is None:  # pragma: no cover
        raise RuntimeError("No se puede guardar la key: falta el Administrador de credenciales")
    keyring.set_password(SERVICE, ACCOUNT, key.strip())


def delete_key() -> None:
    if keyring is None:  # pragma: no cover
        return
    try:
        keyring.delete_password(SERVICE, ACCOUNT)
    except KeyringError:
        pass


def hint(key: str | None) -> str | None:
    """'••••1a2b': nunca la key entera."""
    if not key:
        return None
    return "••••" + key.strip()[-4:]
