from pipeline.fetch import fred


def test_fetch_all_applies_per_series_limit(monkeypatch):
    captured = {}

    def fake_fetch_series(series_id, limit=24):
        captured[series_id] = limit
        return [{"date": "2026-01-01", "value": 1.0}]

    monkeypatch.setattr(fred, "fetch_series", fake_fetch_series)

    fred.fetch_all(["DGS10", "GDPC1", "UNMAPPED"], limit={"DGS10": 260, "GDPC1": 5})

    assert captured["DGS10"] == 260
    assert captured["GDPC1"] == 5
    assert captured["UNMAPPED"] == 24  # not in the mapping, falls back to the default


def test_fetch_all_flat_int_limit_still_works(monkeypatch):
    captured = {}

    def fake_fetch_series(series_id, limit=24):
        captured[series_id] = limit
        return []

    monkeypatch.setattr(fred, "fetch_series", fake_fetch_series)

    fred.fetch_all(["DGS10", "GDPC1"], limit=10)

    assert captured == {"DGS10": 10, "GDPC1": 10}
