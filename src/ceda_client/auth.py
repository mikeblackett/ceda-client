"""Token acquisition, caching, and re-authentication for requests to the
CEDA Archive."""

from http import HTTPStatus
from threading import Lock
from typing import ClassVar, Final

import cattrs as cat
import requests as rq
import requests.adapters as rqh
import requests.auth as rqa
import urllib3 as u3

from ceda_client.converter import converter
from ceda_client.errors import MissingPasswordError
from ceda_client.token import AccessToken

__all__ = ["TokenAuth", "TokenAuthRetryAdapter"]

TOKEN_URL: Final = "https://services.ceda.ac.uk/api/token/create/"
TIMEOUT_SECONDS: Final = 5
DEFAULT_TOKEN_RETRIES: Final = u3.Retry(total=1)
DEFAULT_POOLSIZE: Final = 10


def _create_session(
    max_retries: int | u3.Retry = DEFAULT_TOKEN_RETRIES,
    pool_maxsize: int = DEFAULT_POOLSIZE,
) -> rq.Session:
    """Build the dedicated session used to fetch tokens."""
    session = rq.Session()
    # Ignore proxy settings from the environment: token requests go
    # straight to CEDA's service endpoint.
    session.trust_env = False
    adapter = rqh.HTTPAdapter(
        max_retries=max_retries,
        pool_maxsize=pool_maxsize,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    return session


_auth_session = _create_session()


class TokenAuth(rqa.AuthBase):
    """Requests auth that attaches a cached CEDA access token.

    Tokens are cached at class level, keyed by username, and shared across
    ``TokenAuth`` instances with the same username. The password is only
    required when no fresh token is cached. Fetching is thread-safe:
    concurrent callers for the same username fetch at most once.
    """

    _cache: ClassVar[dict[str, AccessToken]] = {}
    _locks: ClassVar[dict[str, Lock]] = {}
    _converter: ClassVar[cat.Converter] = converter
    _generation: ClassVar[int] = 0
    _generation_lock: ClassVar[Lock] = Lock()

    _username: str
    _password: str | None
    _url: str
    _timeout: float | tuple[float, float]

    def __init__(
        self,
        username: str,
        password: str | None = None,
        *,
        url: str = TOKEN_URL,
        timeout: float | tuple[float, float] = TIMEOUT_SECONDS,
    ) -> None:
        self._username = username
        self._password = password
        self._url = url
        self._timeout = timeout

    def __call__(self, request: rq.PreparedRequest) -> rq.PreparedRequest:
        """Attach the current token's ``Authorization`` header to ``request``."""
        request.headers["Authorization"] = self.token.auth_header
        return request

    @property
    def token(self) -> AccessToken:
        """A fresh access token for this username, fetching one if needed.

        Returns the cached token when it is still fresh, otherwise fetches
        (and caches) a new one.

        Raises:
            MissingPasswordError: If no fresh token is cached and no password was
                provided at construction.
        """
        username = self._username
        password = self._password
        cached = self._cache.get(username)
        if cached is not None and cached.is_fresh:
            return cached
        if password is None:
            raise MissingPasswordError(username)
        with self._locks.setdefault(username, Lock()):  # atomic under the GIL
            cached = self._cache.get(username)
            if cached is not None and cached.is_fresh:
                return cached
            gen = self._generation
            token = self._fetch(username, password)
            if gen == self._generation:
                # avoid resurrecting cached tokens that were cleared mid-flight
                self._cache[username] = token
            return token

    def invalidate(self) -> None:
        """Discard this username's cached token; the next request re-authenticates."""
        self.clear(self._username)

    @classmethod
    def clear(cls, username: str | None = None) -> None:
        """Discard cached tokens, for ``username`` or all when ``username`` is None."""
        with cls._generation_lock:
            # Bump a generation counter so in-flight tokens are not re-cached after the
            # clear.
            cls._generation += 1
        if username is None:
            cls._cache.clear()
        else:
            with cls._locks.setdefault(username, Lock()):
                cls._cache.pop(username, None)

    def _fetch(self, username: str, password: str) -> AccessToken:
        """Exchange credentials for a fresh token at the token endpoint."""
        with _auth_session.post(
            self._url, auth=(username, password), timeout=self._timeout
        ) as r:
            r.raise_for_status()
            return self._converter.structure(r.json(), AccessToken)


class TokenAuthRetryAdapter(rqh.HTTPAdapter):
    """HTTP adapter that transparently re-authenticates on a 401 response.

    If the server rejects a request as unauthorized, the cached token is
    invalidated, the request is re-signed with a fresh token, and the
    request is sent once more.
    """

    def __init__(self, auth: TokenAuth, *args, **kwargs) -> None:
        self._auth = auth
        super().__init__(*args, **kwargs)

    def send(self, request: rq.PreparedRequest, *args, **kwargs) -> rq.Response:
        """Send ``request``, retrying once with a fresh token if it 401s."""
        response = super().send(request, *args, **kwargs)
        if response.status_code == HTTPStatus.UNAUTHORIZED:
            response.close()
            self._auth.invalidate()
            request = self._auth(request)
            response = super().send(request, *args, **kwargs)
        return response
