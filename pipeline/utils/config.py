from functools import lru_cache

import yaml

from pipeline.utils.paths import CONFIG_DIR


@lru_cache(maxsize=None)
def load_yaml(name: str) -> dict:
    """Load and cache a YAML file from config/ by filename, e.g. 'watchlist.yaml'."""
    path = CONFIG_DIR / name
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def watchlist() -> list[dict]:
    return load_yaml("watchlist.yaml")["companies"]


def sector_macro_sensitivity() -> dict:
    return load_yaml("sector_macro_sensitivity.yaml")


def macro_series() -> dict:
    return load_yaml("macro_series.yaml")


def screening_config() -> dict:
    return load_yaml("screening.yaml")
