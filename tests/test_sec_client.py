"""Tests for sec_client.py."""

import pytest

from sec_client import SecConfigError, get_session


def test_get_session_requires_contact_email(monkeypatch):
    monkeypatch.delenv("SEC_CONTACT_EMAIL", raising=False)
    with pytest.raises(SecConfigError):
        get_session()


def test_get_session_puts_contact_in_user_agent(monkeypatch):
    monkeypatch.setenv("SEC_CONTACT_EMAIL", "Test User test@example.com")
    session = get_session()
    assert "test@example.com" in session.headers["User-Agent"]
