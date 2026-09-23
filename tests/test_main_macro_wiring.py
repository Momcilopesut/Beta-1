from pipeline import main


def test_fetch_macro_passes_per_series_history_limits(monkeypatch):
    captured = {}

    def fake_fetch_all(ids, limit=24):
        captured["ids"] = ids
        captured["limit"] = limit
        return {sid: [] for sid in ids} | {"_errors": {}}

    monkeypatch.setattr(main.fred, "fetch_all", fake_fetch_all)

    main.fetch_macro()

    assert isinstance(captured["limit"], dict)
    assert captured["limit"]["DGS10"] == 261
    assert captured["limit"]["GDPC1"] == 5
    assert set(captured["ids"]) == set(captured["limit"].keys())


def test_build_macro_doc_includes_mood_per_series():
    # 13 monthly observations for UNRATE (obs_per_year=12) - enough for a
    # real year-over-year mood reading; falling unemployment is favorable.
    observations = [{"date": f"2025-{(i % 12) + 1:02d}-01", "value": 4.5} for i in range(12)] + [
        {"date": "2026-01-01", "value": 4.0}
    ]
    macro_data = {"UNRATE": observations}
    regime_info = {"regime": "Neutral/Expansion", "signals": {}}

    doc = main.build_macro_doc(macro_data, regime_info, "2026-01-01T00:00:00Z")

    unrate = next(s for s in doc["series"] if s["series_id"] == "UNRATE")
    assert unrate["mood"]["emoji"] == "🙂"
    assert unrate["mood"]["label"] == "Improving"


def test_build_macro_doc_mood_none_without_enough_history():
    macro_data = {"UNRATE": [{"date": "2026-01-01", "value": 4.0}]}
    regime_info = {"regime": "Neutral/Expansion", "signals": {}}

    doc = main.build_macro_doc(macro_data, regime_info, "2026-01-01T00:00:00Z")

    unrate = next(s for s in doc["series"] if s["series_id"] == "UNRATE")
    assert unrate["mood"] is None


def test_risk_free_rate_pct_reads_latest_observation():
    macro_data = {"DGS10": [{"date": "2026-01-01", "value": 3.8}, {"date": "2026-01-02", "value": 4.1}]}
    assert main._risk_free_rate_pct(macro_data, "DGS10") == 4.1


def test_risk_free_rate_pct_missing_series_returns_none():
    assert main._risk_free_rate_pct({}, "DGS10") is None


def test_capital_efficiency_config_has_expected_keys():
    cfg = main.capital_efficiency_config()
    assert "equity_risk_premium_pct" in cfg
    assert "assumed_tax_rate_pct" in cfg
    assert cfg["risk_free_rate_series"] == "DGS10"
