from pipeline.scoring import macro_mood

REGIME_RULES = {"yield_curve_series": "T10Y2Y", "cpi_target_yoy_pct": 2.0}


def _monthly_series(values):
    """13 monthly observations (12 back + latest), oldest first."""
    return [{"date": f"2025-{(i % 12) + 1:02d}-01", "value": v} for i, v in enumerate(values)]


def test_higher_better_favorable():
    cfg = {"obs_per_year": 12, "mood": {"direction": "higher_better", "metric": "pct_change", "thresholds": {"favorable": 1.5, "unfavorable": 0.0}}}
    observations = _monthly_series([100.0] * 12 + [103.0])  # +3% YoY
    mood = macro_mood.compute_mood("PAYEMS", observations, cfg, REGIME_RULES)
    assert mood["emoji"] == "🙂"
    assert mood["label"] == "Improving"
    assert mood["sentiment"] == "favorable"


def test_higher_better_unfavorable():
    cfg = {"obs_per_year": 12, "mood": {"direction": "higher_better", "metric": "pct_change", "thresholds": {"favorable": 2.0, "unfavorable": -1.0}}}
    observations = _monthly_series([100.0] * 12 + [97.0])  # -3% YoY
    mood = macro_mood.compute_mood("INDPRO", observations, cfg, REGIME_RULES)
    assert mood["emoji"] == "😟"
    assert mood["label"] == "Weakening"


def test_lower_better_favorable():
    cfg = {"obs_per_year": 12, "mood": {"direction": "lower_better", "metric": "level_change", "thresholds": {"favorable": -0.3, "unfavorable": 0.5}}}
    observations = _monthly_series([4.5] * 12 + [4.0])  # -0.5pp YoY
    mood = macro_mood.compute_mood("UNRATE", observations, cfg, REGIME_RULES)
    assert mood["emoji"] == "🙂"
    assert mood["label"] == "Improving"


def test_lower_better_unfavorable():
    cfg = {"obs_per_year": 12, "mood": {"direction": "lower_better", "metric": "level_change", "thresholds": {"favorable": -0.3, "unfavorable": 0.5}}}
    observations = _monthly_series([4.0] * 12 + [4.8])  # +0.8pp YoY
    mood = macro_mood.compute_mood("UNRATE", observations, cfg, REGIME_RULES)
    assert mood["emoji"] == "😟"
    assert mood["label"] == "Worsening"


def test_target_near():
    cfg = {"obs_per_year": 12, "mood": {"direction": "target", "metric": "pct_change", "thresholds": {"near": 1.0, "far": 3.0}}}
    observations = _monthly_series([300.0] * 12 + [306.0])  # +2% YoY, right at target
    mood = macro_mood.compute_mood("CPIAUCSL", observations, cfg, REGIME_RULES)
    assert mood["emoji"] == "🙂"
    assert mood["label"] == "Near target"


def test_target_well_above():
    cfg = {"obs_per_year": 12, "mood": {"direction": "target", "metric": "pct_change", "thresholds": {"near": 1.0, "far": 3.0}}}
    observations = _monthly_series([300.0] * 12 + [318.0])  # +6% YoY
    mood = macro_mood.compute_mood("CPIAUCSL", observations, cfg, REGIME_RULES)
    assert mood["emoji"] == "😟"
    assert mood["label"] == "Well above target"


def test_target_deflation_is_always_unfavorable():
    cfg = {"obs_per_year": 12, "mood": {"direction": "target", "metric": "pct_change", "thresholds": {"near": 1.0, "far": 3.0}}}
    observations = _monthly_series([300.0] * 12 + [297.0])  # -1% YoY
    mood = macro_mood.compute_mood("PCEPI", observations, cfg, REGIME_RULES)
    assert mood["emoji"] == "😟"
    assert mood["label"] == "Deflationary reading"


def test_context_calm():
    cfg = {"obs_per_year": 12, "mood": {"direction": "context", "metric": "level_change", "thresholds": {"calm": 0.50, "elevated": 1.50}}}
    observations = _monthly_series([5.25] * 12 + [5.30])  # +0.05pp YoY
    mood = macro_mood.compute_mood("FEDFUNDS", observations, cfg, REGIME_RULES)
    assert mood["emoji"] == "🙂"
    assert mood["label"] == "Calm"


def test_context_volatile():
    cfg = {"obs_per_year": 12, "mood": {"direction": "context", "metric": "level_change", "thresholds": {"calm": 0.50, "elevated": 1.50}}}
    observations = _monthly_series([5.25] * 12 + [3.00])  # -2.25pp YoY
    mood = macro_mood.compute_mood("FEDFUNDS", observations, cfg, REGIME_RULES)
    assert mood["emoji"] == "😟"
    assert mood["label"] == "Volatile"


def test_yield_curve_inversion_overrides_banding():
    cfg = {"obs_per_year": 12, "mood": {"direction": "context", "metric": "level_change", "thresholds": {"calm": 0.30, "elevated": 0.75}}}
    # Barely moved (would otherwise read "Calm"), but currently inverted.
    observations = _monthly_series([-0.10] * 12 + [-0.15])
    mood = macro_mood.compute_mood("T10Y2Y", observations, cfg, REGIME_RULES)
    assert mood["emoji"] == "😰"
    assert mood["label"] == "Inverted"
    assert mood["sentiment"] == "alarm"


def test_non_inverted_curve_uses_ordinary_banding():
    cfg = {"obs_per_year": 12, "mood": {"direction": "context", "metric": "level_change", "thresholds": {"calm": 0.30, "elevated": 0.75}}}
    observations = _monthly_series([0.20] * 12 + [0.25])
    mood = macro_mood.compute_mood("T10Y2Y", observations, cfg, REGIME_RULES)
    assert mood["label"] == "Calm"


def test_insufficient_history_returns_none():
    cfg = {"obs_per_year": 12, "mood": {"direction": "higher_better", "metric": "pct_change", "thresholds": {"favorable": 1.5, "unfavorable": 0.0}}}
    observations = _monthly_series([100.0] * 12 + [103.0])[-6:]  # fewer than 13 points
    assert macro_mood.compute_mood("PAYEMS", observations, cfg, REGIME_RULES) is None


def test_missing_mood_config_returns_none():
    observations = _monthly_series([100.0] * 12 + [103.0])
    assert macro_mood.compute_mood("SOME_SERIES", observations, {"obs_per_year": 12}, REGIME_RULES) is None


def test_empty_observations_returns_none():
    cfg = {"obs_per_year": 12, "mood": {"direction": "higher_better", "metric": "pct_change", "thresholds": {"favorable": 1.5, "unfavorable": 0.0}}}
    assert macro_mood.compute_mood("PAYEMS", [], cfg, REGIME_RULES) is None
