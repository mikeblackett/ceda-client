"""Access token model and expiry logic for CEDA's token endpoint."""

from datetime import UTC, datetime, timedelta
from typing import ClassVar, Final

import attrs as at

__all__ = ["AccessToken", "is_token_expired"]

# Treat a token as expired this long before it actually is, so in-flight
# requests never present a token that will die mid-request.
EXPIRY_MARGIN_MINUTES: Final = 5


def is_token_expired(expires_at: datetime, now: datetime) -> bool:
    """Whether the token expires before ``now + EXPIRY_MARGIN_MINUTES``."""
    if expires_at.tzinfo is None:
        # Assume naive datetimes are in UTC
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at < now + timedelta(minutes=EXPIRY_MARGIN_MINUTES)


@at.define(frozen=True)
class AccessToken:
    """Bearer token issued by CEDA's token endpoint.

    Attribute names are aliased to CEDA's wire format via ``_aliases``.
    """

    value: str = at.field(repr=False)
    expires_at: datetime
    _aliases: ClassVar[dict[str, str]] = {
        "value": "access_token",
        "expires_at": "expires",
    }

    @property
    def is_expired(self) -> bool:
        """Whether the token is expired (or within the refresh margin)."""
        return is_token_expired(self.expires_at, datetime.now(UTC))

    @property
    def is_fresh(self) -> bool:
        """Whether the token is still usable (i.e. not :attr:`is_expired`)."""
        return not self.is_expired

    @property
    def auth_header(self) -> str:
        """The value of the ``Authorization`` header carrying this token."""
        return f"Bearer {self.value}"
