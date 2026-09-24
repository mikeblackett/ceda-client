from abc import ABC
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import ClassVar

import attrs as at

__all__ = ["Directory", "File", "Link", "Listing"]


class ItemType(StrEnum):
    FILE = "file"
    DIRECTORY = "dir"
    LINK = "link"


class Location(StrEnum):
    DISK = "on_disk"
    TAPE = "on_tape"


@at.define(frozen=True, slots=True, kw_only=True)
class _Base(ABC):
    path: Path


@at.define(frozen=True, slots=True, kw_only=True)
class Item(_Base):
    _type: ItemType = at.field(repr=False)
    last_modified: datetime | None = None
    _aliases: ClassVar[dict[str, str]] = {"_type": "type"}

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def directory(self) -> Path:
        return self.path.parent


@at.define(frozen=True, slots=True, kw_only=True)
class File(Item):
    download_url: str
    location: list[Location]
    md5: str
    size: int
    _aliases: ClassVar[dict[str, str]] = {**Item._aliases, "download_url": "download"}

    @property
    def extension(self) -> str:
        return self.path.suffix

    @property
    def on_disk(self) -> bool:
        return Location.DISK in self.location


@at.define(frozen=True, slots=True, kw_only=True)
class Directory(Item): ...


@at.define(frozen=True, slots=True, kw_only=True)
class Link(Item):
    target: str | None = None


@at.define(frozen=True, slots=True, kw_only=True)
class Listing(_Base):
    items: tuple[Directory | File | Link, ...]

    @property
    def files(self) -> tuple[File, ...]:
        return tuple(i for i in self.items if isinstance(i, File))

    @property
    def directories(self) -> tuple[Directory, ...]:
        return tuple(i for i in self.items if isinstance(i, Directory))

    @property
    def links(self) -> tuple[Link, ...]:
        return tuple(i for i in self.items if isinstance(i, Link))
