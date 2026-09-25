"""Custom errors for the CEDA Archive Client."""

from collections.abc import Sequence
from typing import Self


class NotOnDiskError(Exception):
    """Raised when attempting to download a file that is not stored on disk."""

    def __init__(
        self,
        *,
        filename: str,
        location: Sequence[str],
    ) -> None:
        self.filename = filename
        self.location = location
        super().__init__(
            f"only files stored on disk can be downloaded,"
            f" got {filename!r} with location {location!r}."
        )


class ChecksumMismatchError(Exception):
    """Raised when an item's checksum doesn't match the expected value."""

    def __init__(
        self,
        *,
        basename: str,
        expected: str,
        actual: str,
        algorithm: str = "md5",
    ) -> None:
        self.basename = basename
        self.algorithm = algorithm
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"checksum mismatch for {basename!r}: "
            f"expected {algorithm} {expected}, got {actual}"
        )


class MissingPasswordError(RuntimeError):
    """Raised when attempting token (re)authentication with a missing password."""

    def __init__(self, username: str) -> None:
        self.username = username
        super().__init__(
            f"no cached token for {username!r}; a password is required "
            "to (re)authenticate with the CEDA token server."
        )


class DuplicateFilenameError(ValueError):
    """Raised when attempting to download duplicate filenames to the same directory."""

    def __init__(self, filename: str, matches: Sequence[str]) -> None:
        self.filename = filename
        self.matches = matches
        super().__init__(
            f"duplicated filename {filename!r}: "
            f"{', '.join(sorted(matches))} would overwrite each other."
        )


class DuplicateFilenameErrorGroup(ExceptionGroup[DuplicateFilenameError]):
    """Group of ``DuplicateFilenameError`` for a flat download target."""

    @classmethod
    def of(cls, errors: Sequence[DuplicateFilenameError]) -> Self:
        return cls(
            "duplicate file names would overwrite each other in a flat "
            "target; pass mirror_dirs=True to preserve the remote directory "
            "structure, or download into separate target directories.",
            list(errors),
        )
