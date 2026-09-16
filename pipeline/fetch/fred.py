"""FRED (Federal Reserve Economic Data) client. Free, requires an API key."""

import os

from pipeline.utils.http import get_json

BASE_URL = "https://api.stlouisfed.org/fred/series/observations"


class FredError(Exception):
    pass


def fetch_series(series_id: str, limit: int = 24) -> list[dict]:
    """Most recent `limit` observations for a series, oldest first, missing
    ('.') values dropped."""
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        raise FredError("FRED_API_KEY is not set")

    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }
    payload = get_json(BASE_URL, params=params, host_key="fred", min_interval_seconds=0.1)
    observations = payload.get("observations", [])
    cleaned = [
        {"date": o["date"], "value": float(o["value"])}
        for o in observations
        if o.get("value") not in (None, ".", "")
    ]
    cleaned.reverse()
    return cleaned


def fetch_all(series_ids: list[str], limit: int = 24) -> dict:
    """Returns {<series_id>: [...observations], "_errors": {<series_id>: str}}."""
    result: dict = {}
    errors: dict[str, str] = {}
    for sid in series_ids:
        try:
            result[sid] = fetch_series(sid, limit=limit)
        except Exception as exc:  # noqa: BLE001
            errors[sid] = str(exc)
            result[sid] = []
    result["_errors"] = errors
    return result
