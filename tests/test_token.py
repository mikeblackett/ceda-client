from datetime import UTC, datetime, timedelta

import hypothesis as hp
import hypothesis.strategies as st
import pytest as pt  # noqa

from ceda_client.token import AccessToken, EXPIRY_MARGIN_MINUTES


def _token(expires_at: datetime) -> AccessToken:
    return AccessToken(access_token="t", expires=expires_at)


@hp.given(
    offset=st.timedeltas(
        min_value=timedelta(minutes=0),
        max_value=timedelta(days=365),
    )
)
def test_token_is_expired(offset: timedelta):
    expires_at = datetime.now(UTC) - offset
    token = _token(expires_at)
    assert token.is_expired is True


@hp.given(
    offset=st.timedeltas(
        min_value=timedelta(minutes=EXPIRY_MARGIN_MINUTES, seconds=1),
        max_value=timedelta(days=365),
    )
)
def test_token_is_fresh(offset: timedelta):
    expires_at = datetime.now(UTC) + offset
    token = _token(expires_at)
    assert token.is_fresh is True


@hp.given(
    offset=st.timedeltas(
        min_value=timedelta(0), max_value=timedelta(minutes=EXPIRY_MARGIN_MINUTES)
    )
)
def test_token_within_expiry_margin_is_expired(offset: timedelta):
    expires_at = datetime.now(UTC) + offset
    token = _token(expires_at)
    assert token.is_expired is True


@hp.given(
    offset=st.timedeltas(
        min_value=timedelta(0), max_value=timedelta(minutes=EXPIRY_MARGIN_MINUTES)
    )
)
def test_naive_datetime_treated_as_utc(offset: timedelta):
    # The assumption is that datetime strings with no tzinfo are in UTC...
    expires_at = datetime.now(UTC).replace(tzinfo=None) + offset
    token = _token(expires_at)
    assert token.is_expired is True


@hp.given(value=st.text(min_size=1))
def test_auth_header(value: str):
    token = AccessToken(access_token=value, expires=datetime.now(UTC))
    assert token.auth_header == f"Bearer {value}"


def test_token_repr_hides_value():
    secret = "super-secret-token-value"
    token = AccessToken(access_token=secret, expires=datetime.now(UTC))
    assert secret not in repr(token)
