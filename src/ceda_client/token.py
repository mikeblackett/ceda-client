from datetime import UTC, datetime, timedelta
from typing import ClassVar, Final

import attrs as at

__all__ = ["AccessToken", "is_token_expired"]

EXPIRY_MARGIN_MINUTES: Final = 5


def is_token_expired(expires_at: datetime, now: datetime) -> bool:
    if expires_at.tzinfo is None:
        # Assume naive datetimes are in UTC
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at < now + timedelta(minutes=EXPIRY_MARGIN_MINUTES)


@at.define(frozen=True)
class AccessToken:
    value: str = at.field(repr=False)
    expires_at: datetime
    _aliases: ClassVar[dict[str, str]] = {
        "value": "access_token",
        "expires_at": "expires",
    }

    @property
    def is_expired(self) -> bool:
        return is_token_expired(self.expires_at, datetime.now(UTC))

    @property
    def is_fresh(self) -> bool:
        return not self.is_expired

    @property
    def auth_header(self) -> str:
        return f"Bearer {self.value}"
