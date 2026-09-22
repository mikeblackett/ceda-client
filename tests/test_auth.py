from datetime import UTC, datetime, timedelta

import hypothesis.strategies as st
import pytest as pt
import requests as rq
from mock import call
from pytest_mock import MockerFixture

from ceda_client.auth import AccessToken, TokenAuth

USERNAME = "deep_thought"
PASSWORD = "secret"
TOKEN_VALUE = "42"


@st.composite
def access_tokens(
    draw: st.DrawFn,
    value: st.SearchStrategy[str],
    expires_at: st.SearchStrategy[datetime],
):
    return AccessToken(access_token=draw(value), expires=draw(expires_at))


def test_token_fetched(mocker: MockerFixture):
    TokenAuth.clear()
    mock = mocker.patch(
        "ceda_client.auth.TokenAuth._fetch",
        return_value=AccessToken(TOKEN_VALUE, datetime.now(UTC) + timedelta(days=3)),
    )
    TokenAuth(USERNAME, PASSWORD).token
    mock.assert_called_once()
    TokenAuth.clear()


def test_token_returned_from_cache(mocker: MockerFixture):
    cached = AccessToken("cached", datetime.now(UTC) + timedelta(minutes=30))
    TokenAuth._cache[USERNAME] = cached
    mock = mocker.patch(
        "ceda_client.auth.TokenAuth._fetch",
        return_value=AccessToken("fetched", datetime.now(UTC) + timedelta(days=3)),
    )
    assert TokenAuth(USERNAME, PASSWORD).token is cached
    assert TokenAuth(USERNAME).token is cached
    mock.assert_not_called()
    TokenAuth.clear()


def test_expired_token_triggers_refetch(mocker: MockerFixture):
    cached = AccessToken("cached", datetime.now(UTC) - timedelta(minutes=3))
    TokenAuth._cache[USERNAME] = cached
    mock = mocker.patch(
        "ceda_client.auth.TokenAuth._fetch",
        return_value=AccessToken(TOKEN_VALUE, datetime.now(UTC) + timedelta(days=3)),
    )
    assert TokenAuth(USERNAME, PASSWORD).token is not cached
    mock.assert_called_once()
    TokenAuth.clear()


def test_tokens_are_scoped_to_username(mocker: MockerFixture):
    mock = mocker.patch(
        "ceda_client.auth.TokenAuth._fetch",
        return_value=AccessToken(TOKEN_VALUE, datetime.now(UTC) + timedelta(days=3)),
    )
    TokenAuth("paul", "super-secret").token
    TokenAuth("peter", "super-duper-secret").token
    mock.assert_has_calls(
        [call("paul", "super-secret"), call("peter", "super-duper-secret")],
    )
    TokenAuth.clear()


def test_token_requires_password_when_no_cache():
    with pt.raises(RuntimeError):
        TokenAuth("nobody-here").token


def test_call_sets_authorization_header(mocker):
    TokenAuth._cache[USERNAME] = AccessToken(
        TOKEN_VALUE, datetime.now(UTC) + timedelta(days=3)
    )
    try:
        request = rq.PreparedRequest()
        request.prepare(method="GET", url="https://example.com")
        TokenAuth(USERNAME, PASSWORD)(request)
        assert request.headers["Authorization"] == f"Bearer {TOKEN_VALUE}"
    finally:
        TokenAuth.clear()


def test_clear():
    TokenAuth.clear()
    try:
        TokenAuth._cache[USERNAME] = AccessToken(
            "abc", datetime.now(UTC) + timedelta(hours=1)
        )
        assert TokenAuth(USERNAME).clear() is None
        assert USERNAME not in TokenAuth._cache
        TokenAuth._cache[USERNAME] = AccessToken(
            "abc", datetime.now(UTC) + timedelta(hours=1)
        )
        TokenAuth.clear(USERNAME)
        assert USERNAME not in TokenAuth._cache
        TokenAuth.clear()  # clears everything, must not raise
    finally:
        TokenAuth.clear()
