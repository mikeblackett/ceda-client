from datetime import UTC, datetime, timedelta
from typing import Final

import attrs as at

__all__ = ["AccessToken"]

EXPIRY_MARGIN_MINUTES: Final = 5


@at.define(frozen=True)
class AccessToken:
    value: str = at.field(alias="access_token", repr=False)
    expires_at: datetime = at.field(alias="expires")

    @property
    def is_expired(self) -> bool:
        expires = self.expires_at
        if expires.tzinfo is None:
            # Assume naive datetime are in UTC
            expires = expires.replace(tzinfo=UTC)
        return expires < datetime.now(UTC) + timedelta(minutes=EXPIRY_MARGIN_MINUTES)

    @property
    def is_fresh(self) -> bool:
        return not self.is_expired

    @property
    def auth_header(self) -> str:
        return f"Bearer {self.value}"
