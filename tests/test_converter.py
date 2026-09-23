from datetime import UTC, datetime

import hypothesis as hp
import hypothesis.strategies as st
import pytest
from cattrs.errors import ClassValidationError

from ceda_client.auth import AccessToken
from ceda_client.converter import converter
from ceda_client.schema import File, Listing


@hp.given(st.datetimes())
def test_datetime_structure_naive(value: datetime):
    naive = value.replace(tzinfo=None)
    assert converter.structure(naive.isoformat(), datetime) == naive


@hp.given(st.datetimes(timezones=st.just(UTC)))
def test_datetime_structure_with_tz(value: datetime):
    assert converter.structure(value.isoformat(), datetime) == value


@hp.given(st.datetimes())
def test_datetime_unstructure(value: datetime):
    assert converter.unstructure(value, datetime) == value.isoformat()


def test_datetime_invalid_raises():
    with pytest.raises(Exception):  # noqa: B017
        converter.structure("not-a-date", datetime)


def test_access_token_uses_aliases():
    token = converter.structure(
        {"access_token": "abc", "expires": "2025-01-02T03:04:05Z"}, AccessToken
    )
    assert token.value == "abc"
    unstructured = converter.unstructure(token, AccessToken)
    assert set(unstructured) == {"access_token", "expires"}


def test_file_requires_alias_keys():
    data = {
        "path": "/x/y.nc",
        "name": "y.nc",
        "type": "file",
        "location": ["on_disk"],
        "md5": "a" * 32,
        "size": 1,
        "last_modified": None,
    }
    with pytest.raises(ClassValidationError):
        # "download_url" / "_type" are python names, not the wire format
        converter.structure({**data, "download_url": "https://example.com"}, File)
    data["download"] = "https://example.com"
    assert converter.structure(data, File).download_url == "https://example.com"


def test_listing_unstructure_roundtrip():
    data = {
        "path": "/x",
        "items": [
            {
                "path": "/x/y.nc",
                "name": "y.nc",
                "type": "file",
                "location": ["on_disk"],
                "md5": "a" * 32,
                "size": 1,
                "download": "https://example.com/y.nc",
                "last_modified": "2025-01-02T03:04:05",
            },
            {
                "path": "/x/d",
                "name": "d",
                "type": "dir",
                "location": [None],
                "last_modified": None,
            },
        ],
    }
    listing = converter.structure(data, Listing)
    out = converter.unstructure(listing)
    assert str(out["path"]) == "/x"
    assert {i["type"] for i in out["items"]} == {"file", "dir"}
    assert converter.structure(out, Listing).files[0].md5 == "a" * 32
