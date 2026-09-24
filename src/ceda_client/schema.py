"""Data models for CEDA's JSON listing responses."""

from abc import ABC
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import ClassVar

import attrs as at

__all__ = ["Directory", "File", "Link", "Listing"]


class ItemType(StrEnum):
    """Kind of listing item; values match CEDA's wire ``type`` field."""

    FILE = "file"
    DIRECTORY = "dir"
    LINK = "link"


class Location(StrEnum):
    """Where a file's data is stored; values match CEDA's wire format."""

    DISK = "on_disk"
    TAPE = "on_tape"


@at.define(frozen=True, slots=True, kw_only=True)
class _Base(ABC):
    """Base for CEDA resources identified by their remote path."""

    path: Path


@at.define(frozen=True, slots=True, kw_only=True)
class Item(_Base):
    """A single entry in a listing: a file, directory, or link."""

    _type: ItemType = at.field(repr=False)
    last_modified: datetime | None = None
    _aliases: ClassVar[dict[str, str]] = {"_type": "type"}

    @property
    def name(self) -> str:
        """The item's basename."""
        return self.path.name

    @property
    def directory(self) -> Path:
        """The item's parent directory."""
        return self.path.parent


@at.define(frozen=True, slots=True, kw_only=True)
class File(Item):
    """A downloadable file entry in a listing.

    ``location`` is a list because a file may be staged on disk and also
    resident on tape; only files on disk can be downloaded.
    """

    download_url: str
    location: list[Location]
    md5: str
    size: int
    _aliases: ClassVar[dict[str, str]] = {**Item._aliases, "download_url": "download"}

    @property
    def extension(self) -> str:
        """The file's extension, including the leading dot (empty if none)."""
        return self.path.suffix

    @property
    def on_disk(self) -> bool:
        """Whether the file's data is on disk, i.e. downloadable."""
        return Location.DISK in self.location


@at.define(frozen=True, slots=True, kw_only=True)
class Directory(Item):
    """A subdirectory entry in a listing."""


@at.define(frozen=True, slots=True, kw_only=True)
class Link(Item):
    """A symlink entry in a listing; ``target`` is the link destination."""

    target: str | None = None


@at.define(frozen=True, slots=True, kw_only=True)
class Listing(_Base):
    """The contents of one remote directory, keyed by its path."""

    items: tuple[Directory | File | Link, ...]

    @property
    def files(self) -> tuple[File, ...]:
        """Only the file entries of this listing."""
        return tuple(i for i in self.items if isinstance(i, File))

    @property
    def directories(self) -> tuple[Directory, ...]:
        """Only the subdirectory entries of this listing."""
        return tuple(i for i in self.items if isinstance(i, Directory))

    @property
    def links(self) -> tuple[Link, ...]:
        """Only the symlink entries of this listing."""
        return tuple(i for i in self.items if isinstance(i, Link))
