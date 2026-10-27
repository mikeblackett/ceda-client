"""Python client for the CEDA Archive JSON directory
listings and file downloads.

Why this exists: CEDA serves data over DAP2, and DAP2 has no int64 type.
Standard tools such as ``pydap`` therefore cannot download datasets that
contain int64 data. This client uses CEDA's JSON listings (a ``json``
query parameter on any directory URL) and downloads files directly over
HTTP, sidestepping the DAP2 limitation.

If your data has no int64 (and nothing else specific to this client),
prefer a DAP2 tool like ``pydap``.
"""

from importlib import import_module
from importlib.metadata import version
from typing import Any

from ceda_client.auth import TokenAuth
from ceda_client.client import (
    Client,
    DownloadResult,
    FileManifest,
    ResultBatch,
    SkipPolicy,
    Status,
)
from ceda_client.errors import (
    ChecksumMismatchError,
    DuplicateFilenameError,
    DuplicateFilenameErrorGroup,
    MissingPasswordError,
    NotOnDiskError,
    NotOnDiskErrorGroup,
)
from ceda_client.schema import (
    Directory,
    File,
    Item,
    ItemType,
    Link,
    Listing,
    Location,
)
from ceda_client.token import AccessToken

__version__ = version("ceda-client")

__all__ = [
    "AccessToken",
    "ChecksumMismatchError",
    "Client",
    "Directory",
    "DownloadResult",
    "DuplicateFilenameError",
    "DuplicateFilenameErrorGroup",
    "File",
    "FileManifest",
    "Item",
    "ItemType",
    "Link",
    "Listing",
    "Location",
    "MissingPasswordError",
    "NotOnDiskError",
    "NotOnDiskErrorGroup",
    "ResultBatch",
    "SkipPolicy",
    "Status",
    "TokenAuth",
    "__version__",
]

_INTEGRATION_EXPORTS = {
    "DagsterCEDAResource": "ceda_client.integrations.dagster"
}


def __getattr__(name: str) -> Any:
    module_name = _INTEGRATION_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    # cache so subsequent access is a plain attribute lookup
    # and name shows up in `dir()` or `vars()`.
    globals()[name] = value
    return value
