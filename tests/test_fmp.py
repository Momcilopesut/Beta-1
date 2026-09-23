"""Tests for pipeline.fetch.fmp - specifically the dot-ticker hyphen
fallback (FMP spells share classes like "BRK-B", not "BRK.B")."""

import os
from unittest.mock import patch

import pytest

from pipeline.fetch import fmp


@pytest.fixture(autouse=True)
def fmp_api_key():
    with patch.dict(os.environ, {"FMP_API_KEY": "test-key"}):
        yield


def test_get_retries_with_hyphen_for_dot_tickers():
    def fake_get_json(url, *, params, **kwargs):
        if params["symbol"] == "BRK.B":
            raise Exception("402 Payment Required")
        assert params["symbol"] == "BRK-B"
        return {"ok": True}

    with patch("pipeline.fetch.fmp.get_json", side_effect=fake_get_json):
        result = fmp._get("quote", "BRK.B")

    assert result == {"ok": True}


def test_get_dot_ticker_propagates_error_when_both_forms_fail():
    with patch("pipeline.fetch.fmp.get_json", side_effect=Exception("402 Payment Required")):
        with pytest.raises(Exception, match="402 Payment Required"):
            fmp._get("quote", "BRK.B")


def test_get_non_dot_ticker_only_tries_once():
    calls = []

    def fake_get_json(url, *, params, **kwargs):
        calls.append(params["symbol"])
        return {"ok": True}

    with patch("pipeline.fetch.fmp.get_json", side_effect=fake_get_json):
        result = fmp._get("quote", "AAPL")

    assert result == {"ok": True}
    assert calls == ["AAPL"]
