"""Minimal HTTP GET-JSON helper with per-host rate limiting and retry/backoff.

This is a scheduled batch job hitting a handful of hosts a few hundred times
per run, not a high-throughput service — a plain function with a small
in-memory "last call per host" map is enough; no session pooling or async
needed.
"""

import logging
import time
from collections import defaultdict
from typing import Any

import requests

logger = logging.getLogger(__name__)

_last_request_at: dict[str, float] = defaultdict(float)


class HttpError(Exception):
    """Raised when a request fails after all retries are exhausted."""


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
    if host_key and min_interval_seconds > 0:
        elapsed = time.monotonic() - _last_request_at[host_key]
        wait = min_interval_seconds - elapsed
        if wait > 0:
            time.sleep(wait)

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=timeout)
            if host_key:
                _last_request_at[host_key] = time.monotonic()
            if response.status_code == 429 or response.status_code >= 500:
                raise HttpError(f"HTTP {response.status_code} from {url}")
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, HttpError) as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                backoff = 2**attempt
                logger.warning("Request to %s failed (%s); retrying in %ss", url, exc, backoff)
                time.sleep(backoff)

    raise HttpError(f"Failed to fetch {url} after {max_retries} attempts: {last_exc}") from last_exc
