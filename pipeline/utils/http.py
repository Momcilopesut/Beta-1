"""Minimal HTTP GET helper with per-host rate limiting and retry/backoff.

Used both by the sequential batch pipeline and by app.py's on-demand lookup
route, which fires a single ticker's per-source fetches concurrently
across threads to keep latency down - so the rate-limit bookkeeping below
is lock-protected even though nothing in the batch pipeline itself needs
that.

`impersonate` (passed through get_json/get_text) routes the request
through curl_cffi instead of plain `requests` - needed for
pipeline.fetch.sec_edgar/filing_text: SEC's Akamai front end has been
observed 403ing *every* www.sec.gov/data.sec.gov request from a real
residential connection with a fully compliant User-Agent and browser-like
headers, while the exact same request succeeds from an actual browser.
That's TLS/HTTP2 fingerprinting, not a header or rate check - curl_cffi
replicates a real browser's TLS handshake (impersonate="chrome") rather
than plain `requests`'/urllib3's own distinguishable one. Confirmed by a
real user: plain `requests`/curl 403, curl_cffi with impersonate="chrome"
200, same machine, same minute. FMP/FRED/Stooq haven't shown this problem,
so they're left on plain `requests` - impersonate defaults to None (no
behavior change) everywhere else.

When impersonating, a caller's own `headers` are NOT forwarded - a Chrome
TLS handshake paired with a non-browser header set (e.g. an identifying
User-Agent) still got 403'd in practice, so curl_cffi's own
internally-consistent browser header set is left alone instead. Worth
being explicit about the tradeoff this implies: SEC's own EDGAR API
documentation asks automated callers to self-identify via User-Agent;
fully impersonating a browser goes against that spirit, and is only done
here because SEC's current front end was observed blocking a compliant,
self-identified request outright regardless, leaving no way to reach
this public, free, unauthenticated data over HTTP otherwise.
"""

import logging
import threading
import time
from collections import defaultdict
from typing import Any

import requests
from curl_cffi import requests as curl_requests

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
    for the same host_key concurrently (see app.py's /api/lookup route)."""
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
    impersonate: str | None = None,
) -> Any:
    if host_key and min_interval_seconds > 0:
        wait = _reserve_slot(host_key, min_interval_seconds)
        if wait > 0:
            time.sleep(wait)

    # curl_cffi doesn't share `requests`' exception hierarchy, so the
    # impersonate path needs a broader catch for the same kind of failure
    # (connection error, timeout, bad status) the narrower tuple already
    # covers for every existing plain-`requests` caller - not broadened
    # for them, so a real bug there still surfaces immediately as before.
    retry_on = Exception if impersonate else (requests.RequestException, HttpError)

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            if impersonate:
                # Deliberately NOT passing our own `headers` (e.g.
                # edgar_headers()'s identifying User-Agent) here - curl_cffi's
                # impersonate presets set a full, internally-consistent
                # browser header set matched to that TLS fingerprint,
                # and merging our own User-Agent on top of it was observed
                # still getting 403'd: a TLS handshake that looks like Chrome
                # but a header set that doesn't is its own, possibly even
                # more obvious tell than an honest non-browser signature.
                response = curl_requests.get(url, params=params, timeout=timeout, impersonate=impersonate)
            else:
                response = requests.get(url, params=params, headers=headers, timeout=timeout)
            if response.status_code == 429 or response.status_code >= 500:
                raise HttpError(f"HTTP {response.status_code} from {url}")
            response.raise_for_status()
            return response
        except retry_on as exc:
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
    impersonate: str | None = None,
) -> Any:
    """GET a URL and parse the JSON body, with retry/backoff on 429/5xx/network errors.

    Pass the same `host_key` (e.g. "sec_edgar") across calls that must share a
    rate budget; `min_interval_seconds` is then enforced between consecutive
    calls under that key, regardless of which specific URL is requested.

    impersonate: e.g. "chrome" - routes through curl_cffi instead of plain
    `requests` (see this module's docstring for why: SEC's Akamai front end
    TLS-fingerprints plain `requests`/curl as non-browser traffic and 403s
    it even with compliant headers).
    """
    response = _get_with_retry(
        url,
        params=params,
        headers=headers,
        host_key=host_key,
        min_interval_seconds=min_interval_seconds,
        timeout=timeout,
        max_retries=max_retries,
        impersonate=impersonate,
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
    impersonate: str | None = None,
) -> str:
    """GET a URL and return the raw response body as text (e.g. CSV). Same
    retry/backoff/rate-limit behavior as get_json, including `impersonate`."""
    response = _get_with_retry(
        url,
        params=params,
        headers=headers,
        host_key=host_key,
        min_interval_seconds=min_interval_seconds,
        timeout=timeout,
        max_retries=max_retries,
        impersonate=impersonate,
    )
    return response.text
