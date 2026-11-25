"""Tests for pipeline/utils/http.py's impersonate="chrome" dispatch - added
after a real user's machine got 403'd by SEC's Akamai front end on every
www.sec.gov/data.sec.gov request (TLS/HTTP2 fingerprinting plain
requests/curl as non-browser traffic), fixed by routing those calls
through curl_cffi instead. Every other caller (FMP, FRED, Stooq) doesn't
pass impersonate and must keep behaving exactly as before."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from pipeline.utils.http import HttpError, get_json


def _ok_response(payload):
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


def test_get_json_uses_plain_requests_by_default():
    with (
        patch("pipeline.utils.http.requests.get", return_value=_ok_response({"a": 1})) as mock_requests_get,
        patch("pipeline.utils.http.curl_requests.get") as mock_curl_get,
    ):
        result = get_json("https://example.com")

    assert result == {"a": 1}
    mock_requests_get.assert_called_once()
    mock_curl_get.assert_not_called()


def test_get_json_uses_curl_cffi_when_impersonating():
    with (
        patch("pipeline.utils.http.requests.get") as mock_requests_get,
        patch("pipeline.utils.http.curl_requests.get", return_value=_ok_response({"b": 2})) as mock_curl_get,
    ):
        result = get_json("https://www.sec.gov/files/company_tickers.json", impersonate="chrome")

    assert result == {"b": 2}
    mock_requests_get.assert_not_called()
    mock_curl_get.assert_called_once()
    assert mock_curl_get.call_args.kwargs["impersonate"] == "chrome"


def test_get_json_retries_curl_cffi_failures_then_raises_http_error():
    with (
        patch("pipeline.utils.http.curl_requests.get", side_effect=RuntimeError("boom")) as mock_curl_get,
        patch("pipeline.utils.http.time.sleep"),
    ):
        with pytest.raises(HttpError):
            get_json("https://www.sec.gov/files/company_tickers.json", impersonate="chrome", max_retries=2)

    assert mock_curl_get.call_count == 2


def test_get_json_plain_requests_path_does_not_swallow_unrelated_bugs():
    """Only the impersonate path gets the broader exception catch (curl_cffi
    doesn't share requests' exception hierarchy) - a plain-requests caller
    hitting an unrelated bug (not a RequestException) should still surface
    immediately, not get silently retried and reported as an HttpError."""
    with patch("pipeline.utils.http.requests.get", side_effect=TypeError("unrelated bug")):
        with pytest.raises(TypeError):
            get_json("https://example.com")


def test_get_json_plain_requests_still_retries_real_request_exceptions():
    with (
        patch("pipeline.utils.http.requests.get", side_effect=requests.ConnectionError("no route")) as mock_requests_get,
        patch("pipeline.utils.http.time.sleep"),
    ):
        with pytest.raises(HttpError):
            get_json("https://example.com", max_retries=2)

    assert mock_requests_get.call_count == 2
