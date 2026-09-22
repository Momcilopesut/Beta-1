"""Optional on-disk raw-response cache for local dev iteration.

Disabled by default. Enable with PIPELINE_CACHE=1 so repeated local runs
against the same tickers don't re-spend FMP/SEC/FRED rate-limit budget while
iterating on scoring or qualitative-layer code. Never used in CI/scheduled
runs.
"""

import json
import os
from pathlib import Path
from typing import Any

from pipeline.utils.paths import CACHE_DIR


def enabled() -> bool:
    return os.environ.get("PIPELINE_CACHE", "").lower() in ("1", "true", "yes")


def _path_for(key: str) -> Path:
    safe = key.replace("/", "__")
    return CACHE_DIR / f"{safe}.json"


def read(key: str) -> Any | None:
    path = _path_for(key)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write(key: str, value: Any) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(_path_for(key), "w", encoding="utf-8") as f:
        json.dump(value, f)
