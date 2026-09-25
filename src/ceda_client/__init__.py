"""Python client for the CEDA (UK Climate Data Archive) JSON directory
listings and file downloads.

Why this exists: CEDA serves data over DAP2, and DAP2 has no int64 type.
Standard tools such as ``pydap`` therefore cannot download datasets that
contain int64 data. This client uses CEDA's JSON listings (a ``json``
query parameter on any directory URL) and downloads files directly over
HTTP, sidestepping the DAP2 limitation.

If your data has no int64 (and nothing else specific to this client),
prefer a DAP2 tool like ``pydap``.
"""

from ceda_client.auth import TokenAuth
from ceda_client.client import Client, DownloadResult, ResultBatch, SkipPolicy, Status
from ceda_client.schema import Directory, File, Item, ItemType, Link, Listing, Location
from ceda_client.token import AccessToken

__all__ = [
    "AccessToken",
    "Client",
    "Directory",
    "DownloadResult",
    "File",
    "Item",
    "ItemType",
    "Link",
    "Listing",
    "Location",
    "ResultBatch",
    "SkipPolicy",
    "Status",
    "TokenAuth",
]
