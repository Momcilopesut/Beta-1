"""Persists Layer 3 (qualitative) AI output, keyed by the URLs of the 10-K/
10-Q/8-K it was generated from. 10-Ks are filed annually and this pipeline
runs weekly - without this cache, every scheduled refresh would re-fetch the
same filing text and re-spend a Claude call per qualifying company for an
answer that can't have changed. Keying on all three filing URLs (not just
the 10-K's) means a new quarter's 10-Q or a fresh 8-K correctly invalidates
the cache even when the 10-K itself hasn't changed. A cache hit (same three
filing URLs as last time) skips it entirely.

Lives under data/qualitative_cache/, passed the same base_dir
(writer.output_dir(dry_run)) as the rest of data/ - so it's committed
alongside company/watchlist/macro JSON in a real run, and confined to
data/.dry-run/ (gitignored) during --dry-run, never touching the real
cache. Unrelated to the dev-only pipeline/fetch/cache.py, which caches raw
API responses locally and is never used in CI.
"""

import json
from pathlib import Path


def _path(base_dir: Path, ticker: str) -> Path:
    return base_dir / "qualitative_cache" / f"{ticker}.json"


def read(base_dir: Path, ticker: str) -> dict | None:
    path = _path(base_dir, ticker)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write(base_dir: Path, ticker: str, filing_urls: dict[str, str | None], qualitative: dict) -> None:
    path = _path(base_dir, ticker)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            {"filing_urls": filing_urls, "qualitative": qualitative},
            f,
            indent=2,
            sort_keys=True,
            default=str,
        )
        f.write("\n")
