"""Sesión HTTP común con reintentos y backoff ante 429/5xx o sin conexión.

Mientras espera para reintentar avisa a `retry_listener` (la ventana lo muestra como
progreso: "Sin conexión, reintentando en 4 s…"), y nunca espera más de MAX_WAIT por
reintento aunque el servidor pida más (`Retry-After`).
"""

from __future__ import annotations

import time
from typing import Callable
from urllib.parse import urlparse

import requests

RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_WAIT = 30.0  # segundos como máximo por espera, aunque Retry-After pida más

# Callable(host, motivo, segundos) con motivo "offline" | "busy" | "error"; None = nadie escucha.
retry_listener: Callable[[str, str, float], None] | None = None


class ApiError(RuntimeError):
    """Error de red o de la API. `kind`: "offline", "http" o "busy" (429)."""

    def __init__(self, message: str, kind: str = "http", status: int | None = None):
        super().__init__(message)
        self.kind, self.status = kind, status


def _notify(url: str, reason: str, wait: float) -> None:
    if retry_listener is not None:
        try:
            retry_listener(urlparse(url).hostname or url, reason, wait)
        except Exception:  # noqa: BLE001 - un aviso nunca debe romper una petición
            pass


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    retries: int = 4,
    min_interval: float = 0.0,
    timeout: float = 30,
    **kwargs,
) -> requests.Response:
    delay = 1.0
    for attempt in range(retries + 1):
        if min_interval:
            time.sleep(min_interval)
        try:
            resp = session.request(method, url, timeout=timeout, **kwargs)
        except (requests.ConnectionError, requests.Timeout) as exc:
            if attempt == retries:
                raise ApiError(f"{method} {url}: {exc}", kind="offline") from exc
            _notify(url, "offline", delay)
            time.sleep(delay)
            delay *= 2
            continue

        if resp.status_code in RETRY_STATUS and attempt < retries:
            retry_after = resp.headers.get("Retry-After")
            wait = float(retry_after) if retry_after and retry_after.isdigit() else delay
            wait = min(wait, MAX_WAIT)
            _notify(url, "busy" if resp.status_code == 429 else "error", wait)
            time.sleep(wait)
            delay *= 2
            continue
        return resp
    raise ApiError(f"{method} {url}: demasiados reintentos")  # pragma: no cover
