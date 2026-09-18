"""Layer 2: a fast, deterministic quant screen - pure function, no API
calls, no LLM. Distinct from the weighted short/long-term scores in
pipeline/scoring/short_term.py and long_term.py: those rank "how good",
this answers a narrower yes/no question first (does the company clear a
baseline quality bar) so the expensive layers (qualitative filing-text
reasoning, per company.html) only run on names worth the spend. See
config/quant_score_thresholds.yaml for the thresholds themselves.
"""

from pipeline.utils.config import quant_score_thresholds


def _metric_value(metrics: dict, key: str) -> float | None:
    if key == "revenue_cagr_pct":
        return metrics.get("revenue_cagr_5yr_pct") if metrics.get("revenue_cagr_5yr_pct") is not None else metrics.get("revenue_cagr_3yr_pct")
    if key == "eps_growth_cagr_pct":
        return (
            metrics.get("eps_growth_cagr_5yr_pct")
            if metrics.get("eps_growth_cagr_5yr_pct") is not None
            else metrics.get("eps_growth_cagr_3yr_pct")
        )
    return metrics.get(key)


def build_quant_scorecard(metrics: dict) -> dict:
    """Returns {"metrics": {key: {value, threshold, higher_is_better, pass}},
    "informational": {key: value}, "evaluated": int, "passed": int,
    "quant_score_pct": float|None, "gate_pass": bool|None}."""
    config = quant_score_thresholds()
    results: dict[str, dict] = {}
    evaluated = 0
    passed = 0

    for key, spec in config["metrics"].items():
        value = _metric_value(metrics, key)
        if value is None:
            results[key] = {
                "value": None,
                "threshold": spec["threshold"],
                "higher_is_better": spec["higher_is_better"],
                "pass": None,
                "label": spec["label"],
            }
            continue
        ok = value >= spec["threshold"] if spec["higher_is_better"] else value <= spec["threshold"]
        results[key] = {
            "value": value,
            "threshold": spec["threshold"],
            "higher_is_better": spec["higher_is_better"],
            "pass": ok,
            "label": spec["label"],
        }
        evaluated += 1
        passed += int(ok)

    informational = {key: metrics.get(key) for key in config.get("informational_metrics", [])}

    quant_score_pct = (passed / evaluated * 100) if evaluated else None
    gate_pass = quant_score_pct is not None and quant_score_pct / 100 >= config["gate_pass_fraction"]

    return {
        "metrics": results,
        "informational": informational,
        "evaluated": evaluated,
        "passed": passed,
        "quant_score_pct": quant_score_pct,
        "gate_pass": gate_pass if evaluated else None,
    }
