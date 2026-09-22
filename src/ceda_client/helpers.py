import requests as rq
import requests.adapters as rqa
import requests.auth as rq_auth
import urllib3 as u3

__all__ = ["create_session"]


def create_session(
    max_retries: int | u3.Retry = 0,
    pool_maxsize: int = 1,
    auth: rq_auth.AuthBase | None = None,
) -> rq.Session:
    session = rq.Session()
    session.auth = auth
    session.trust_env = False
    adapter = rqa.HTTPAdapter(
        max_retries=max_retries,
        pool_maxsize=pool_maxsize,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session
