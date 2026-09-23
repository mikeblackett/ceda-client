from datetime import UTC, datetime, timedelta
from typing import Final

import attrs as at

__all__ = ["AccessToken", "is_token_expired"]

EXPIRY_MARGIN_MINUTES: Final = 5


def is_token_expired(expires_at: datetime, now: datetime) -> bool:
    if expires_at.tzinfo is None:
        # Assume naive datetime are in UTC
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at < now + timedelta(minutes=EXPIRY_MARGIN_MINUTES)


@at.define(frozen=True)
class AccessToken:
    value: str = at.field(alias="access_token", repr=False)
    expires_at: datetime = at.field(alias="expires")

    @property
    def is_expired(self) -> bool:
        return is_token_expired(self.expires_at, datetime.now(UTC))

    @property
    def is_fresh(self) -> bool:
        return not self.is_expired

    @property
    def auth_header(self) -> str:
        return f"Bearer {self.value}"
