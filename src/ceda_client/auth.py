from http import HTTPStatus
from threading import Lock
from typing import ClassVar, Final

import cattrs as cat
import requests as rq
import requests.adapters as rqh
import requests.auth as rqa
import urllib3 as u3

from ceda_client.converter import converter
from ceda_client.token import AccessToken

__all__ = ["TokenAuth", "TokenAuthRetryAdapter"]

TOKEN_URL: Final = "https://services.ceda.ac.uk/api/token/create/"
TIMEOUT_SECONDS: Final = 5
DEFAULT_TOKEN_RETRIES: Final = u3.Retry(total=1, allowed_methods=["post"])
DEFAULT_POOLSIZE: Final = 10


def _create_session(
    max_retries: int | u3.Retry = DEFAULT_TOKEN_RETRIES,
    pool_maxsize: int = DEFAULT_POOLSIZE,
) -> rq.Session:
    session = rq.Session()
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
        request.headers["Authorization"] = self.token.auth_header
        return request

    @property
    def token(self) -> AccessToken:
        username = self._username
        password = self._password
        cached = self._cache.get(username)
        if cached is not None and cached.is_fresh:
            return cached
        if password is None:
            raise RuntimeError(
                f"no cached token for {username!r}; you must provide a password."
            )
        with self._locks.setdefault(username, Lock()):  # atomic under the GIL
            cached = self._cache.get(username)
            if cached is not None and cached.is_fresh:
                return cached
            gen = self._generation
            token = self._fetch(username, password)
            if gen == self._generation:
                # avoid resurrecting cached tokens that were cleared in-flight
                self._cache[username] = token
            return token

    def invalidate(self) -> None:
        self.clear(self._username)

    @classmethod
    def clear(cls, username: str | None = None) -> None:
        with cls._generation_lock:
            cls._generation += 1
        if username is None:
            cls._cache.clear()
        else:
            with cls._locks.setdefault(username, Lock()):
                cls._cache.pop(username, None)

    def _fetch(self, username: str, password: str) -> AccessToken:
        with _auth_session.post(
            self._url, auth=(username, password), timeout=self._timeout
        ) as r:
            r.raise_for_status()
            return self._converter.structure(r.json(), AccessToken)


class TokenAuthRetryAdapter(rqh.HTTPAdapter):
    def __init__(self, auth: TokenAuth, *args, **kwargs) -> None:
        self._auth = auth
        super().__init__(*args, **kwargs)

    def send(self, request: rq.PreparedRequest, *args, **kwargs) -> rq.Response:
        response = super().send(request, *args, **kwargs)
        if response.status_code == HTTPStatus.UNAUTHORIZED:
            response.close()
            self._auth.invalidate()
            request = self._auth(request)
            response = super().send(request, *args, **kwargs)
        return response
