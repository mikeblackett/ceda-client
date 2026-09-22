from datetime import datetime, timedelta, timezone

import pytest
import requests

from ceda_client.auth import AccessToken, TokenAuth

from .conftest import FAKE_TOKEN, PASS, USER


def _token(expires_at: datetime) -> AccessToken:
    return AccessToken(access_token="t", expires=expires_at)


def test_token_not_expired():
    assert _token(datetime.now(timezone.utc) + timedelta(hours=1)).is_expired is False


def test_token_expired():
    assert _token(datetime.now(timezone.utc) - timedelta(hours=1)).is_expired is True


def test_token_within_expiry_margin_is_expired():
    # 5 minute safety margin
    assert _token(datetime.now(timezone.utc) + timedelta(minutes=1)).is_expired is True
    assert (
        _token(datetime.now(timezone.utc) + timedelta(minutes=10)).is_expired is False
    )


def test_naive_datetime_treated_as_utc():
    assert _token(datetime.now() + timedelta(hours=1)).is_expired is False
    assert _token(datetime.now() - timedelta(hours=1)).is_expired is True


def test_auth_header():
    assert _token(datetime.now(timezone.utc)).auth_header == "Bearer t"


def test_token_repr_hides_value():
    secret = "super-secret-token-value"
    token = AccessToken(access_token=secret, expires=datetime.now(timezone.utc))
    assert secret not in repr(token)


def test_cached_token_returned_without_network():
    TokenAuth.clear(USER)
    cached = AccessToken(
        access_token="cached", expires=datetime.now(timezone.utc) + timedelta(hours=1)
    )
    TokenAuth._cache[USER] = cached
    try:
        assert TokenAuth(USER, None).token is cached
    finally:
        TokenAuth.clear(USER)


def test_expired_cached_token_triggers_refetch_or_error():
    TokenAuth.clear(USER)
    try:
        # no password -> cannot refetch -> RuntimeError
        with pytest.raises(RuntimeError):
            TokenAuth(USER, None).token
    finally:
        TokenAuth.clear(USER)


def test_token_requires_password_when_no_cache():
    with pytest.raises(RuntimeError):
        TokenAuth("nobody-here", None).token


def test_call_sets_authorization_header():
    TokenAuth.clear(USER)
    TokenAuth._cache[USER] = AccessToken(
        access_token="abc", expires=datetime.now(timezone.utc) + timedelta(hours=1)
    )
    try:
        request = requests.PreparedRequest()
        request.prepare(method="GET", url="https://example.com")
        TokenAuth(USER, None)(request)
        assert request.headers["Authorization"] == "Bearer abc"
    finally:
        TokenAuth.clear(USER)


def test_fetch_token_from_server(ceda_server):
    TokenAuth.clear(USER)
    try:
        handler = ceda_server.handler
        auth = TokenAuth(USER, PASS, url=f"{ceda_server.url}token")
        token = auth.token
        assert token.value == FAKE_TOKEN
        assert len(handler.token_hits) == 1
        # second access hits the cache, not the server
        assert auth.token is token
        assert len(handler.token_hits) == 1
    finally:
        TokenAuth.clear(USER)


def test_fetch_token_wrong_password(ceda_server):
    TokenAuth.clear(USER)
    try:
        auth = TokenAuth(USER, "wrong", url=f"{ceda_server.url}token")
        with pytest.raises(requests.HTTPError):
            auth.token
    finally:
        TokenAuth.clear(USER)


def test_invalidate_and_clear():
    TokenAuth.clear(USER)
    try:
        TokenAuth._cache[USER] = AccessToken(
            access_token="abc", expires=datetime.now(timezone.utc) + timedelta(hours=1)
        )
        assert TokenAuth(USER, None).invalidate() is None
        assert USER not in TokenAuth._cache
        TokenAuth._cache[USER] = AccessToken(
            access_token="abc", expires=datetime.now(timezone.utc) + timedelta(hours=1)
        )
        TokenAuth.clear(USER)
        assert USER not in TokenAuth._cache
        TokenAuth.clear()  # clears everything, must not raise
    finally:
        TokenAuth.clear()
