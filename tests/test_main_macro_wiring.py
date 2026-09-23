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
