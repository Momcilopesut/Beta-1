"""Minimal HTTP GET helper with per-host rate limiting and retry/backoff.

Used both by the sequential batch pipeline and by the on-demand lookup
endpoint (api/lookup.py), which fires a single ticker's per-source fetches
concurrently across threads to keep latency down - so the rate-limit
bookkeeping below is lock-protected even though nothing in the batch
pipeline itself needs that.
"""

import logging
import threading
import time
from collections import defaultdict
from typing import Any

import requests

logger = logging.getLogger(__name__)

_last_request_at: dict[str, float] = defaultdict(float)
_rate_limit_lock = threading.Lock()


class HttpError(Exception):
    """Raised when a request fails after all retries are exhausted."""


def _reserve_slot(host_key: str, min_interval_seconds: float) -> float:
    """Atomically claims the next available call slot for this host_key and
    returns how long the caller should sleep before proceeding. Slots are
    scheduled min_interval_seconds apart regardless of how long any given
    request takes, which - unlike timing spacing off when the previous
    request *finished* - stays correct when multiple threads reserve slots
    for the same host_key concurrently (see api/lookup.py)."""
    with _rate_limit_lock:
        now = time.monotonic()
        earliest = max(now, _last_request_at[host_key] + min_interval_seconds)
        _last_request_at[host_key] = earliest
        return max(0.0, earliest - now)


def _get_with_retry(
    url: str,
    *,
    params: dict | None,
    headers: dict | None,
    host_key: str | None,
    min_interval_seconds: float,
    timeout: float,
    max_retries: int,
) -> requests.Response:
    if host_key and min_interval_seconds > 0:
        wait = _reserve_slot(host_key, min_interval_seconds)
        if wait > 0:
            time.sleep(wait)

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=timeout)
            if response.status_code == 429 or response.status_code >= 500:
                raise HttpError(f"HTTP {response.status_code} from {url}")
            response.raise_for_status()
            return response
        except (requests.RequestException, HttpError) as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                backoff = 2**attempt
                logger.warning("Request to %s failed (%s); retrying in %ss", url, exc, backoff)
                time.sleep(backoff)

    raise HttpError(f"Failed to fetch {url} after {max_retries} attempts: {last_exc}") from last_exc


def get_json(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    host_key: str | None = None,
    min_interval_seconds: float = 0.0,
    timeout: float = 15.0,
    max_retries: int = 3,
) -> Any:
    """GET a URL and parse the JSON body, with retry/backoff on 429/5xx/network errors.

    Pass the same `host_key` (e.g. "sec_edgar") across calls that must share a
    rate budget; `min_interval_seconds` is then enforced between consecutive
    calls under that key, regardless of which specific URL is requested.
    """
    response = _get_with_retry(
        url,
        params=params,
        headers=headers,
        host_key=host_key,
        min_interval_seconds=min_interval_seconds,
        timeout=timeout,
        max_retries=max_retries,
    )
    return response.json()


def get_text(
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
    host_key: str | None = None,
    min_interval_seconds: float = 0.0,
    timeout: float = 15.0,
    max_retries: int = 3,
) -> str:
    """GET a URL and return the raw response body as text (e.g. CSV). Same
    retry/backoff/rate-limit behavior as get_json."""
    response = _get_with_retry(
        url,
        params=params,
        headers=headers,
        host_key=host_key,
        min_interval_seconds=min_interval_seconds,
        timeout=timeout,
        max_retries=max_retries,
    )
    return response.text
