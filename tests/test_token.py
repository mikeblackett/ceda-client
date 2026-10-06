from datetime import UTC, datetime, timedelta

import hypothesis as hp
import hypothesis.strategies as st
import pytest as pt

from ceda_client.token import (
    EXPIRY_MARGIN_MINUTES,
    AccessToken,
    _is_expired,
)

from .strategies import access_tokens

_MARGIN = timedelta(minutes=EXPIRY_MARGIN_MINUTES)


class TestExpiryMargin:
    @pt.fixture
    def now(self) -> datetime:
        return datetime.now(UTC)

    def test_now_is_expired(self, now: datetime) -> None:
        assert _is_expired(now, now) is True

    def test_within_margin_is_expired(self, now: datetime) -> None:
        assert _is_expired(now + _MARGIN - timedelta(seconds=1), now) is True

    def test_margin_boundary_is_not_expired(self, now: datetime) -> None:
        # Strict '<': a token expiring exactly at the margin is not expired.
        assert _is_expired(now + _MARGIN, now) is False

    @hp.given(
        now=st.datetimes(
            min_value=datetime(2000, 1, 1, tzinfo=UTC),
            max_value=datetime(2100, 1, 1, tzinfo=UTC),
            timezones=st.just(UTC),
        ),
        offset=st.timedeltas(
            min_value=timedelta(days=-1), max_value=timedelta(days=1)
        ),
    )
    def test_expired_iff_within_margin(
        self, now: datetime, offset: timedelta
    ) -> None:
        expires_at = now + offset
        assert _is_expired(expires_at, now) is (offset < _MARGIN)

    def test_naive_datetimes_are_treated_as_utc(self, now: datetime) -> None:
        assert (
            _is_expired((now - timedelta(seconds=1)).replace(tzinfo=None), now)
            is True
        )
        assert _is_expired((now + _MARGIN).replace(tzinfo=None), now) is False


@hp.given(access_tokens(epoch=datetime.now(UTC) - timedelta(days=2)))
def test_past_tokens_are_expired(token: AccessToken) -> None:
    assert token.is_expired is True


@hp.given(
    access_tokens(epoch=datetime.now(UTC), min_timedelta=timedelta(hours=1))
)
def test_future_tokens_are_fresh(token: AccessToken) -> None:
    assert token.is_fresh is True


@hp.given(value=st.text(min_size=1))
def test_auth_header(value: str) -> None:
    token = AccessToken(value=value, expires_at=datetime.now(UTC))
    assert token.auth_header == f"Bearer {value}"


def test_token_repr_hides_value() -> None:
    secret = "super-secret-token-value"
    token = AccessToken(value=secret, expires_at=datetime.now(UTC))
    assert secret not in repr(token)
