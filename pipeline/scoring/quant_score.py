"""Layer 2: a fast, deterministic quant screen - pure function, no API
calls, no LLM. A narrow yes/no question (does the company clear a baseline
balance-sheet/cash-flow safety bar) so the expensive qualitative layer only
runs on names worth the spend. See config/quant_score_thresholds.yaml for
the thresholds themselves.
"""

from pipeline.utils.config import quant_score_thresholds


def build_quant_scorecard(metrics: dict) -> dict:
    """Returns {"metrics": {key: {value, threshold, higher_is_better, pass}},
    "informational": {key: value}, "evaluated": int, "passed": int,
    "quant_score_pct": float|None, "gate_pass": bool|None}."""
    config = quant_score_thresholds()
    results: dict[str, dict] = {}
    evaluated = 0
    passed = 0

    for key, spec in config["metrics"].items():
        value = metrics.get(key)
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
