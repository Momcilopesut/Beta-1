"""Writes the pipeline's generated JSON output, consumed directly by the
static frontend.

Every function takes the target base directory explicitly: normal runs pass
DATA_DIR (data/, committed to git); --dry-run runs pass DATA_DIR/.dry-run
(gitignored) so local experimentation never dirties the tracked data/ files.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from pipeline.scoring.performance import WINDOWS
from pipeline.utils.paths import DATA_DIR


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def output_dir(dry_run: bool) -> Path:
    return (DATA_DIR / ".dry-run") if dry_run else DATA_DIR


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True, default=str)
        f.write("\n")


def write_company(base_dir: Path, ticker: str, company_doc: dict) -> None:
    _write_json(base_dir / "companies" / f"{ticker}.json", company_doc)


def write_watchlist(base_dir: Path, companies_summary: list[dict], generated_at: str) -> None:
    _write_json(base_dir / "watchlist.json", {"generated_at": generated_at, "companies": companies_summary})


def write_performance_picks(
    base_dir: Path, picks_by_sector: dict, generated_at: str, universe_size: int, top_n_per_sector: int
) -> None:
    """picks_by_sector: {sector: {window_key: [summaries]}} from
    pipeline.scoring.performance.select_top_performers. WINDOWS is written
    alongside it so the frontend has each window's display label without
    hardcoding it separately from the scoring module that defines it."""
    _write_json(
        base_dir / "performance_picks.json",
        {
            "generated_at": generated_at,
            "universe_size": universe_size,
            "top_n_per_sector": top_n_per_sector,
            "windows": [{"key": key, "label": label} for key, label, *_ in WINDOWS],
            "picks_by_sector": picks_by_sector,
        },
    )


def write_macro(base_dir: Path, macro_doc: dict) -> None:
    _write_json(base_dir / "macro.json", macro_doc)


def write_filings_digest(base_dir: Path, digest_doc: dict) -> None:
    _write_json(base_dir / "filings_digest.json", digest_doc)


def write_meta(base_dir: Path, meta_doc: dict) -> None:
    _write_json(base_dir / "meta.json", meta_doc)
