from datetime import UTC, datetime, timedelta

import pytest as pt
import requests as rq
from pytest_mock import MockerFixture

from ceda_client.auth import TokenAuth
from ceda_client.token import AccessToken

from .conftest import FAKE_TOKEN, PASS, USER


def test_returns_cached_token(fresh_cache, mocker: MockerFixture):
    # fresh_cache fixture populates cache with fresh USER: FAKE_TOKEN
    mock = mocker.patch(
        "ceda_client.auth.TokenAuth._fetch",
        return_value=AccessToken(
            "fetched-token-xyz", datetime.now(UTC) + timedelta(days=3)
        ),
    )

    token = TokenAuth(USER, PASS).token
    assert token.value == FAKE_TOKEN
    token = TokenAuth(USER).token
    assert token.value == FAKE_TOKEN

    mock.assert_not_called()


def test_fetches_fresh_token(stale_cache, mocker: MockerFixture):
    # stale_cache fixture populates cache with stale USER: FAKE_TOKEN
    fetched = AccessToken("fresh-token-xyz", datetime.now(UTC) + timedelta(days=3))
    mock = mocker.patch(
        "ceda_client.auth.TokenAuth._fetch",
        return_value=fetched,
    )

    token = TokenAuth(USER, PASS).token

    assert token is fetched
    mock.assert_called_once()


def test_fetches_token_when_cache_empty(mocker: MockerFixture):
    TokenAuth.clear()
    fetched = AccessToken("fresh-token-xyz", datetime.now(UTC) + timedelta(days=3))
    mock = mocker.patch(
        "ceda_client.auth.TokenAuth._fetch",
        return_value=fetched,
    )

    token = TokenAuth(USER, PASS).token

    assert token is fetched
    mock.assert_called_once_with(USER, PASS)

    assert TokenAuth(USER).token is fetched
    mock.assert_called_once()


def test_token_requires_password_when_no_cache():
    with pt.raises(RuntimeError):
        TokenAuth("nobody-here").token


def test_tokens_are_scoped_to_username(fresh_cache, mocker: MockerFixture):
    fresh = AccessToken("fresh-token-xyz", datetime.now(UTC) + timedelta(days=3))
    mock = mocker.patch(
        "ceda_client.auth.TokenAuth._fetch",
        return_value=fresh,
    )
    credentials = ("new_user", "super-secret")

    TokenAuth(USER, PASS).token
    TokenAuth(*credentials).token

    mock.assert_called_once_with(*credentials)


def test_call_sets_authorization_header(fresh_cache, mocker: MockerFixture):
    mock = mocker.patch(
        # mock _fetch so this test does not depend on previous tests passing
        "ceda_client.auth.TokenAuth._fetch",
        return_value=AccessToken(
            "never-returned", datetime.now(UTC) + timedelta(hours=1)
        ),
    )
    request = rq.PreparedRequest()
    request.prepare(method="GET", url="https://example.com")

    TokenAuth(USER, PASS)(request)

    assert request.headers["Authorization"] == f"Bearer {FAKE_TOKEN}"
    mock.assert_not_called()


def test_clear(fresh_cache):
    try:
        assert USER in TokenAuth._cache
        assert TokenAuth(USER).invalidate() is None
        assert USER not in TokenAuth._cache
        TokenAuth._cache[USER] = AccessToken(
            "abc", datetime.now(UTC) + timedelta(hours=1)
        )
        TokenAuth.clear(USER)
        assert USER not in TokenAuth._cache
        TokenAuth.clear()  # clears everything, must not raise
    finally:
        TokenAuth.clear()
