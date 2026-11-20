"""Sesión HTTP común con reintentos y backoff ante 429/5xx."""

from __future__ import annotations

import time

import requests

RETRY_STATUS = {429, 500, 502, 503, 504}


class ApiError(RuntimeError):
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
                raise ApiError(f"{method} {url}: {exc}") from exc
            time.sleep(delay)
            delay *= 2
            continue

        if resp.status_code in RETRY_STATUS and attempt < retries:
            retry_after = resp.headers.get("Retry-After")
            wait = float(retry_after) if retry_after and retry_after.isdigit() else delay
            time.sleep(wait)
            delay *= 2
            continue
        return resp
    raise ApiError(f"{method} {url}: demasiados reintentos")  # pragma: no cover
