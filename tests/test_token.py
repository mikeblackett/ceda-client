from datetime import UTC, datetime, timedelta

import hypothesis as hp
import hypothesis.strategies as st

from ceda_client.token import EXPIRY_MARGIN_MINUTES, AccessToken, is_token_expired

from .strategies import access_tokens

_MARGIN = timedelta(minutes=EXPIRY_MARGIN_MINUTES)
_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def test_expired_at_margin_boundary_is_fresh():
    # Strict '<': a token expiring exactly at the margin is not expired.
    assert is_token_expired(_NOW + _MARGIN, _NOW) is False


def test_expired_just_before_margin():
    assert is_token_expired(_NOW + _MARGIN - timedelta(seconds=1), _NOW) is True


def test_expired_when_expiring_now():
    assert is_token_expired(_NOW, _NOW) is True


def test_expired_when_in_past():
    assert is_token_expired(_NOW - timedelta(seconds=1), _NOW) is True


def test_naive_expires_treated_as_utc():
    assert (
        is_token_expired((_NOW - timedelta(seconds=1)).replace(tzinfo=None), _NOW)
        is True
    )
    assert is_token_expired((_NOW + _MARGIN).replace(tzinfo=None), _NOW) is False


@hp.given(
    now=st.datetimes(
        min_value=datetime(2000, 1, 1, tzinfo=UTC),
        max_value=datetime(2100, 1, 1, tzinfo=UTC),
        timezones=st.just(UTC),
    ),
    offset=st.timedeltas(min_value=timedelta(days=-1), max_value=timedelta(days=1)),
)
def test_expired_iff_within_margin(now: datetime, offset: timedelta):
    expires_at = now + offset
    assert is_token_expired(expires_at, now) is (offset < _MARGIN)


@hp.given(access_tokens(epoch=datetime.now(UTC) - timedelta(days=2)))
def test_property_expired_for_past_token(token: AccessToken):
    assert token.is_expired is True


@hp.given(access_tokens(epoch=datetime.now(UTC), min_timedelta=timedelta(hours=1)))
def test_property_fresh_for_future_token(token: AccessToken):
    assert token.is_fresh is True


@hp.given(value=st.text(min_size=1))
def test_auth_header(value: str):
    token = AccessToken(access_token=value, expires=datetime.now(UTC))
    assert token.auth_header == f"Bearer {value}"


def test_token_repr_hides_value():
    secret = "super-secret-token-value"
    token = AccessToken(access_token=secret, expires=datetime.now(UTC))
    assert secret not in repr(token)
