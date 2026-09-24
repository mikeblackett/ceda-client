import hashlib
import io
import re
import threading
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import StrEnum
from typing import (
    Any,
    Final,
    Self,
    cast,
)
from urllib.parse import urljoin
from uuid import uuid4

import requests as rq
import upath as up
import urllib3 as u3

from ceda_client.auth import TokenAuth, TokenAuthRetryAdapter
from ceda_client.converter import converter
from ceda_client.schema import File, Listing
from ceda_client.token import AccessToken

__all__ = ["Client", "Result", "ResultBatch"]


class SkipPolicy(StrEnum):
    """How to treat a target that may already exist."""

    CHECKSUM = "skip_checksum"
    """Skip if exists and md5 matches"""
    EXISTS = "skip_exists"
    """Skip if exists"""
    OVERWRITE = "overwrite"
    """Always (re)write"""
    SIZE = "size"
    """Skip if exists and size matches"""


class Status(StrEnum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


CEDA_ENDPOINT_URL: Final = "https://data.ceda.ac.uk/"
DEFAULT_WORKERS: Final = 8
DEFAULT_RETRIES: Final = 1
DEFAULT_POOLSIZE: Final = 10
DEFAULT_SKIP_POLICY: Final = SkipPolicy.CHECKSUM
DEFAULT_CONNECT_TIMEOUT_SECONDS: Final = 3.05
DEFAULT_READ_TIMEOUT_SECONDS: Final = 180


@dataclass(frozen=True)
class Result:
    file: File
    path: up.UPath
    status: Status
    error: Exception | None = None

    @classmethod
    def succeed(cls, file: File, path: up.UPath) -> Self:
        return cls(file, path, Status.SUCCESS)

    @classmethod
    def skip(cls, file: File, path: up.UPath) -> Self:
        return cls(file, path, Status.SKIPPED)

    @classmethod
    def fail(cls, file: File, path: up.UPath, error: Exception) -> Self:
        return cls(file, path, Status.FAILED, error)


@dataclass(frozen=True)
class ResultBatch:
    results: tuple[Result, ...]
    counter: Counter = field(init=False)
    success: list[Result] = field(init=False)
    failed: list[Result] = field(init=False)
    skipped: list[Result] = field(init=False)

    def __post_init__(self) -> None:
        counter = Counter(r.status for r in self.results)
        object.__setattr__(self, "counter", counter)
        for status in Status:
            object.__setattr__(
                self,
                status.value,
                [r for r in self.results if r.status is status],
            )


class Client:
    username: str
    url: str
    max_retries: int | u3.Retry
    max_workers: int
    pool_maxsize: int
    connect_timeout: float | None
    read_timeout: float | None

    def __init__(
        self,
        username: str,
        password: str | None = None,
        *,
        max_retries: int | u3.Retry = DEFAULT_RETRIES,
        max_workers: int = DEFAULT_WORKERS,
        pool_maxsize: int = DEFAULT_POOLSIZE,
        connect_timeout: float | None = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        read_timeout: float | None = DEFAULT_READ_TIMEOUT_SECONDS,
        url: str = CEDA_ENDPOINT_URL,
    ) -> None:
        self._auth = TokenAuth(username, password)
        self._session: rq.Session | None = None

        self.username = username
        self.max_retries = max_retries
        self.max_workers = max_workers
        self.pool_maxsize = pool_maxsize
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.url = url

    @property
    def token(self) -> AccessToken:
        return self._auth.token

    @property
    def session(self) -> rq.Session:
        if self._session is None:
            self._session = self._create_session()
        return self._session

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_args: object) -> None:
        self.close()

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    def _create_session(self) -> rq.Session:
        session = rq.Session()
        session.auth = self._auth
        session.trust_env = False
        adapter = TokenAuthRetryAdapter(
            auth=self._auth,
            max_retries=self.max_retries,
            pool_maxsize=self.pool_maxsize,
        )
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def resolve_url(self, path: str) -> str:
        return urljoin(self.url, path.lstrip("/"))

    def get_json_listing(self, path: str) -> dict[str, Any]:
        url = self.resolve_url(path)
        with self.session.get(
            url,
            params={"json": ""},
            timeout=(self.connect_timeout, self.read_timeout),
        ) as response:
            response.raise_for_status()
            data = response.json()
        return data

    def get_listing(self, path: str) -> Listing:
        return converter.structure(self.get_json_listing(path), Listing)

    def get_files(
        self,
        path: str,
        extension: str | None = None,
        pattern: str | re.Pattern | None = None,
    ) -> list[File]:
        result = []
        listing = self.get_listing(path)
        for file in listing.files:
            if extension and file.extension != extension:
                continue
            if pattern and not re.search(pattern, file.name):
                continue
            result.append(file)
        return result

    def download(
        self,
        file: File,
        target: up.UPath,
        *,
        mirror_dirs: bool = False,
        skip_policy: SkipPolicy = DEFAULT_SKIP_POLICY,
        chunk_size: int | None = None,
    ) -> Result:
        if not file.on_disk:
            raise ValueError(
                f"only files stored on disk are available for download, got {file.location!r}"
            )
        path = _ensure_target(target)
        return self._stream(
            file=file,
            out=_target_for(file, path, mirror_dirs),
            session=self.session,
            skip_policy=skip_policy,
            chunk_size=chunk_size,
            timeout=(self.connect_timeout, self.read_timeout),
        )

    def download_multi(
        self,
        files: Sequence[File],
        target: up.UPath,
        *,
        mirror_dirs: bool = False,
        session_factory: Callable[[], rq.Session] | None = None,
        skip_policy: SkipPolicy = DEFAULT_SKIP_POLICY,
        max_workers: int | None = None,
        chunk_size: int | None = None,
    ) -> ResultBatch:
        if not mirror_dirs:
            _check_unique_basenames(files)
        path = _ensure_target(target)
        max_workers = max_workers or self.max_workers
        return self._stream_batch(
            files,
            path,
            mirror_dirs=mirror_dirs,
            session_factory=session_factory or self._create_session,
            skip_policy=skip_policy,
            chunk_size=chunk_size,
            max_workers=max_workers,
            timeout=(self.connect_timeout, self.read_timeout),
        )

    def _stream(
        self,
        file: File,
        out: up.UPath,
        session: rq.Session,
        chunk_size: int | None,
        skip_policy: SkipPolicy,
        timeout: tuple[float | None, float | None],
    ) -> Result:
        out.parent.mkdir(parents=True, exist_ok=True)
        if _file_exists(file, out, skip_policy):
            return Result.skip(file, out)
        digest = hashlib.md5(usedforsecurity=False)
        tmp = out.with_name(f"{out.name}.{uuid4().hex}.part")
        try:
            with session.get(
                file.download_url, stream=True, timeout=timeout
            ) as response:
                response.raise_for_status()
                with tmp.open("wb") as f:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        f.write(chunk)
                        digest.update(chunk)
                if file.md5 and digest.hexdigest() != file.md5.casefold():
                    raise ValueError(
                        f"checksum failed for {file.name}: "
                        f"expected {file.md5}, got {digest.hexdigest()}"
                    )
                tmp.replace(out)
        except Exception as error:  # noqa: BLE001
            tmp.unlink(missing_ok=True)
            return Result.fail(file, out, error)
        return Result.succeed(file, out)

    def _stream_batch(
        self,
        files: Sequence[File],
        path: up.UPath,
        mirror_dirs: bool,
        session_factory: Callable[[], rq.Session],
        skip_policy: SkipPolicy,
        chunk_size: int | None,
        max_workers: int,
        timeout: tuple[float | None, float | None],
    ) -> ResultBatch:
        local = threading.local()
        created: list[rq.Session] = []
        lock = threading.Lock()

        def session_for_thread() -> rq.Session:
            session = getattr(local, "session", None)
            if session is None:
                session = session_factory()
                local.session = session
                with lock:
                    created.append(session)
            return session

        def task(file: File) -> Result:
            # wrap submission to push session resolution onto the worker, not the main thread.
            return self._stream(
                file=file,
                out=_target_for(file, path, mirror_dirs),
                session=session_for_thread(),
                skip_policy=skip_policy,
                chunk_size=chunk_size,
                timeout=timeout,
            )

        raw_results: list[Result] = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            try:
                futures = tuple(executor.submit(task, f) for f in files)
                for future in as_completed(futures):
                    raw_results.append(future.result())
            except (KeyboardInterrupt, SystemExit) as error:
                executor.shutdown(cancel_futures=True)
                raise error  # noqa: TRY201
            finally:
                for session in created:
                    session.close()

        results = ResultBatch(tuple(raw_results))
        return results


def _ensure_target(path: up.UPath) -> up.UPath:
    if path.exists() and not path.is_dir():
        raise NotADirectoryError(f"path is not a directory: {path!r}.")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _target_for(file: File, path: up.UPath, mirror_dirs: bool) -> up.UPath:
    if mirror_dirs:
        return path.joinpath(file.path.as_posix().lstrip("/"))
    return path.joinpath(file.name)


def _check_unique_basenames(files: Sequence[File]) -> None:
    seen: dict[str, list[str]] = {}
    for file in files:
        seen.setdefault(file.name.lower(), []).append(file.path.as_posix())
    dupes = {name: paths for name, paths in seen.items() if len(paths) > 1}
    if dupes:
        details = "; ".join(
            f"{name!r}: {', '.join(sorted(paths))}"
            for name, paths in sorted(dupes.items())
        )
        raise ValueError(
            "duplicate file names would overwrite each other in a flat target: "
            f"{details}. Pass mirror_dirs=True to preserve the remote directory "
            "structure, or download into separate target directories."
        )


def _file_exists(
    file: File, path: up.UPath, policy: SkipPolicy = DEFAULT_SKIP_POLICY
) -> bool:
    match policy:
        case SkipPolicy.EXISTS:
            return path.exists()
        case SkipPolicy.SIZE:
            return _verify_file_size(path, file.size)
        case SkipPolicy.CHECKSUM:
            return _verify_file_size(path, file.size) and _verify_checksum(
                path, file.md5
            )
        case SkipPolicy.OVERWRITE:
            return False


def _verify_file_size(path: up.UPath, size: int) -> bool:
    return path.exists() and (path.stat().st_size == size)


def _verify_checksum(path: up.UPath, md5: str) -> bool:
    # TODO: checksum only works for local filesystem files
    if not path.exists():
        return False
    with path.open("rb") as file:
        digest = hashlib.file_digest(
            cast("io.RawIOBase | io.BufferedIOBase", file), "md5"
        )
    return digest.hexdigest() == md5
