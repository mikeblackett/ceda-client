from threading import Lock
from typing import ClassVar, Final

import cattrs as cat
import requests as rq
import requests.auth as rqa
import urllib3 as u3

from ceda_client.converter import converter
from ceda_client.helpers import create_session
from ceda_client.token import AccessToken

__all__ = ["TokenAuth"]

TOKEN_URL: Final = "https://services.ceda.ac.uk/api/token/create/"
TIMEOUT_SECONDS: Final = 5
DEFAULT_RETRIES: Final = u3.Retry(total=1, allowed_methods=["post"])
DEFAULT_POOLSIZE: Final = 10


_session = create_session(max_retries=DEFAULT_RETRIES, pool_maxsize=DEFAULT_POOLSIZE)


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
    ):
        self._username = username
        self._password = password
        self._url = url
        self._timeout = timeout

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

    def __call__(self, request: rq.PreparedRequest) -> rq.PreparedRequest:
        request.headers["Authorization"] = self.token.auth_header
        return request

    @classmethod
    def clear(cls, username: str | None = None) -> None:
        if username is None:
            cls._cache.clear()
        else:
            with cls._locks.setdefault(username, Lock()):
                cls._cache.pop(username, None)
        with cls._generation_lock:
            cls._generation += 1

    def _fetch(self, username: str, password: str) -> AccessToken:
        with _session.post(
            self._url, auth=(username, password), timeout=self._timeout
        ) as r:
            r.raise_for_status()
            return self._converter.structure(r.json(), AccessToken)
