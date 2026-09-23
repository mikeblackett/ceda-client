import re
from datetime import datetime, timedelta

import hypothesis.errors as er
import hypothesis.strategies as st

from ceda_client.token import AccessToken

BASE64_STRING_REGEX = re.compile(
    r"^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$"
)


@st.composite
def access_tokens(
    draw: st.DrawFn,
    epoch: datetime,
    min_timedelta: timedelta | None = None,
    max_timedelta: timedelta | None = None,
    tokens: st.SearchStrategy[str] | None = None,
):
    if tokens is None:
        tokens = st.from_regex(regex=BASE64_STRING_REGEX)

    if min_timedelta is None:
        min_timedelta = timedelta(0)
    if max_timedelta is None:
        max_timedelta = timedelta(days=1)
    if max_timedelta < min_timedelta:
        raise er.InvalidArgument(f"cannot have {max_timedelta=} < {min_timedelta=}")

    if epoch.tzinfo is None:
        timezones = st.just(None)
    else:
        timezones = st.just(epoch.tzinfo)

    return AccessToken(
        access_token=draw(tokens),
        expires=draw(
            st.datetimes(
                min_value=epoch + min_timedelta,
                max_value=epoch + max_timedelta,
                timezones=timezones,
            )
        ),
    )
