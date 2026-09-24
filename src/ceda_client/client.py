"""High-level CEDA client: listings, filtering, and file downloads."""

import hashlib
import io
import re
import threading
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum, auto
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

__all__ = ["Client", "DownloadResult", "ResultBatch"]


class SkipPolicy(Enum):
    """How to treat a target that may already exist."""

    CHECKSUM = auto()
    """Skip if exists and md5 matches"""
    EXISTS = auto()
    """Skip if exists"""
    OVERWRITE = auto()
    """Always (re)write"""
    SIZE = auto()
    """Skip if exists and size matches"""


class Status(Enum):
    """Outcome of a single download attempt."""

    SUCCESS = auto()
    SKIPPED = auto()
    FAILED = auto()


CEDA_ENDPOINT_URL: Final = "https://data.ceda.ac.uk/"
DEFAULT_WORKERS: Final = 8
DEFAULT_REQUEST_RETRIES: Final = 1
DEFAULT_POOLSIZE: Final = 10
DEFAULT_SKIP_POLICY: Final = SkipPolicy.CHECKSUM
DEFAULT_CONNECT_TIMEOUT_SECONDS: Final = 3.05
DEFAULT_READ_TIMEOUT_SECONDS: Final = 180


@dataclass(frozen=True)
class DownloadResult:
    """Outcome of downloading a single file."""

    file: File
    target: up.UPath
    status: Status
    error: Exception | None = None

    @classmethod
    def succeed(cls, file: File, target: up.UPath) -> Self:
        """A result for a successful download."""
        return cls(file, target, Status.SUCCESS)

    @classmethod
    def skip(cls, file: File, target: up.UPath) -> Self:
        """A result for a file skipped by the skip policy."""
        return cls(file, target, Status.SKIPPED)

    @classmethod
    def fail(cls, file: File, target: up.UPath, error: Exception) -> Self:
        """A result for a failed download; ``error`` is the cause."""
        return cls(file, target, Status.FAILED, error)


@dataclass(frozen=True)
class ResultBatch:
    """An immutable batch of download results with precomputed status buckets."""

    results: tuple[DownloadResult, ...]
    counter: Counter = field(init=False)
    success: list[DownloadResult] = field(init=False)
    failed: list[DownloadResult] = field(init=False)
    skipped: list[DownloadResult] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "counter", Counter(r.status for r in self.results))
        object.__setattr__(
            self, "success", [r for r in self.results if r.status is Status.SUCCESS]
        )
        object.__setattr__(
            self, "skipped", [r for r in self.results if r.status is Status.SKIPPED]
        )
        object.__setattr__(
            self, "failed", [r for r in self.results if r.status is Status.FAILED]
        )


class Client:
    """Client for CEDA's JSON directory listings and file downloads.

    Handles token acquisition/caching, HTTP session management, directory
    listings, and single or parallel file downloads with checksum
    verification. Usable as a context manager, which closes the session.
    """

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
        max_retries: int | u3.Retry = DEFAULT_REQUEST_RETRIES,
        max_workers: int = DEFAULT_WORKERS,
        pool_maxsize: int = DEFAULT_POOLSIZE,
        connect_timeout: float | None = DEFAULT_CONNECT_TIMEOUT_SECONDS,
        read_timeout: float | None = DEFAULT_READ_TIMEOUT_SECONDS,
        url: str = CEDA_ENDPOINT_URL,
    ) -> None:
        """Create a client for the CEDA data endpoint.

        Args:
            username: CEDA username.
            password: CEDA password; only needed to fetch the first token,
                since tokens are cached at class level by username.
            max_retries: Retries for data requests: a count, or an
                ``urllib3.Retry`` for finer control.
            max_workers: Thread pool size for ``download_multi``.
            pool_maxsize: HTTP connection pool size per session.
            connect_timeout: Seconds to wait when connecting, or None.
            read_timeout: Seconds to wait between read bytes, or None.
            url: Base URL of the data endpoint.
        """
        self._auth = TokenAuth(username, password)

        self.username = username
        self.max_retries = max_retries
        self.max_workers = max_workers
        self.pool_maxsize = pool_maxsize
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.url = url

        self._session: rq.Session | None = self._create_session()

    @property
    def token(self) -> AccessToken:
        """The current (cached or freshly fetched) access token."""
        return self._auth.token

    @property
    def session(self) -> rq.Session:
        """The HTTP session, recreated lazily after ``close``."""
        if self._session is None:
            self._session = self._create_session()
        return self._session

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_args: object) -> None:
        self.close()

    def close(self) -> None:
        """Close the HTTP session; a new one is created on next use."""
        if self._session is not None:
            self._session.close()
            self._session = None

    def _create_session(self) -> rq.Session:
        """Build an HTTP session with token auth and 401 re-auth retry."""
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
        """Resolve ``path`` against the base URL, tolerating a leading slash."""
        return urljoin(self.url, path.lstrip("/"))

    def get_json_listing(self, path: str) -> dict[str, Any]:
        """Fetch the raw JSON listing for a remote directory.

        Raises:
            rq.HTTPError: If the request fails (e.g. 404 for a bad path).
        """
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
        """Fetch and parse the listing for a remote directory."""
        return converter.structure(self.get_json_listing(path), Listing)

    def get_files(
        self,
        path: str,
        extension: str | None = None,
        pattern: str | re.Pattern | None = None,
    ) -> list[File]:
        """List the files in a remote directory, filtered by name.

        Args:
            path: Remote directory to list.
            extension: If given, only files with this extension (e.g. ``".nc"``).
            pattern: If given, only files whose name matches this regex.
        """
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
    ) -> DownloadResult:
        """Download a single file into the ``target`` directory.

        The file is streamed to a temporary ``.part`` sibling whose md5 is
        checked against the listing's, then atomically renamed into place.

        Args:
            file: The file to download.
            target: Directory to download into (created if missing).
            mirror_dirs: If True, preserve the remote directory structure
                under ``target``; otherwise the file goes directly in
                ``target``.
            skip_policy: How to treat a target that may already exist.
            chunk_size: Read size for the streamed response, or None.

        Raises:
            ValueError: If the file is not stored on disk (e.g. tape only).
            NotADirectoryError: If ``target`` exists and is not a directory.
        """
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
        """Download multiple files in parallel into the ``target`` directory.

        Each worker thread uses its own HTTP session. Failures and skips
        are reported in the returned :class:`ResultBatch`, not raised.

        Args:
            files: Files to download.
            target: Directory to download into (created if missing).
            mirror_dirs: Preserve the remote directory structure under
                ``target``; also disables the duplicate-basename check.
            session_factory: Override how worker sessions are created
                (mainly for tests).
            skip_policy: How to treat a target that may already exist.
            max_workers: Thread pool size, defaulting to the client's.
            chunk_size: Read size for the streamed responses, or None.

        Raises:
            ValueError: If two files share a basename and ``mirror_dirs``
                is False, since they would overwrite each other.
            NotADirectoryError: If ``target`` exists and is not a directory.
        """
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
    ) -> DownloadResult:
        """Stream ``file`` to ``out``, verifying its md5 checksum.

        Never raises for download problems: failures are reported as a
        FAILED result, and the temp file is removed on any failure.
        """
        out.parent.mkdir(parents=True, exist_ok=True)
        if _should_skip(file, out, skip_policy):
            return DownloadResult.skip(file, out)
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
            return DownloadResult.fail(file, out, error)
        return DownloadResult.succeed(file, out)

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
        """Download ``files`` in a thread pool, one session per worker thread.

        Sessions are created lazily per thread so the number of connections
        stays bounded by ``max_workers``; all of them are closed when the
        pool shuts down, even on KeyboardInterrupt.
        """
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

        def task(file: File) -> DownloadResult:
            # wrap submission to push session resolution onto the worker, not the main thread.
            return self._stream(
                file=file,
                out=_target_for(file, path, mirror_dirs),
                session=session_for_thread(),
                skip_policy=skip_policy,
                chunk_size=chunk_size,
                timeout=timeout,
            )

        raw_results: list[DownloadResult] = []
        try:
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
    """Create ``path`` if needed; raise if it exists as a file."""
    if path.exists() and not path.is_dir():
        raise NotADirectoryError(f"path is not a directory: {path!r}.")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _target_for(file: File, path: up.UPath, mirror_dirs: bool) -> up.UPath:
    """The local destination for ``file`` under ``path``."""
    if mirror_dirs:
        return path.joinpath(file.path.as_posix().lstrip("/"))
    return path.joinpath(file.name)


def _check_unique_basenames(files: Sequence[File]) -> None:
    """Raise ValueError if any two files share a basename (case-insensitive)."""
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


def _should_skip(
    file: File, path: up.UPath, policy: SkipPolicy = DEFAULT_SKIP_POLICY
) -> bool:
    """Whether an existing ``path`` satisfies the download skip policy."""
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
    """Whether ``path`` exists and its size matches the remote file's."""
    return path.exists() and (path.stat().st_size == size)


def _verify_checksum(path: up.UPath, md5: str) -> bool:
    """Whether ``path`` exists and its md5 matches the remote file's."""
    # TODO: checksum only works for local filesystem files
    if not path.exists():
        return False
    with path.open("rb") as file:
        digest = hashlib.file_digest(
            cast("io.RawIOBase | io.BufferedIOBase", file), "md5"
        )
    return digest.hexdigest() == md5
