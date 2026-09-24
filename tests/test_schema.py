import json
from pathlib import Path

import pytest

from ceda_client.converter import converter
from ceda_client.schema import (
    Directory,
    File,
    ItemType,
    Link,
    Listing,
    Location,
)

FIXTURE = Path(__file__).parent / "fixtures" / "real_listing.json"


@pytest.fixture
def real_listing() -> dict:
    return json.loads(FIXTURE.read_text())


def test_real_listing_structures(real_listing):
    listing = converter.structure(real_listing, Listing)
    assert listing.path == Path("/mixed")
    assert len(listing.items) == 5


def test_real_listing_item_types(real_listing):
    listing = converter.structure(real_listing, Listing)
    assert len(listing.files) == 2
    assert len(listing.directories) == 2
    assert sum(isinstance(i, Link) for i in listing.items) == 1


def test_file_fields(real_listing):
    file = next(
        f
        for f in converter.structure(real_listing, Listing).files
        if f.name == "00README"
    )
    assert file.path == Path("/neodc/00README")
    assert file.name == "00README"
    assert file.directory == Path("/neodc")
    assert file.extension == ""
    assert file.md5 == "77be50d2fc75a30d173eb231934ab647"
    assert file.size == 369
    assert file.download_url.startswith("https://dap.ceda.ac.uk/")
    assert file._type is ItemType.FILE
    assert file.on_disk is True
    assert file.last_modified is not None


def test_directory_null_location_structures():
    directory = next(
        d
        for d in converter.structure(
            json.loads(FIXTURE.read_text()), Listing
        ).directories
        if d.name == "arsf"
    )
    assert directory._type is ItemType.DIRECTORY


def test_missing_last_modified_defaults_to_none():
    listing = converter.structure(json.loads(FIXTURE.read_text()), Listing)
    ard4ceos = next(i for i in listing.items if i.name == "ard4ceos")
    assert isinstance(ard4ceos, Directory)
    assert ard4ceos.last_modified is None


def test_link_structures():
    listing = converter.structure(json.loads(FIXTURE.read_text()), Listing)
    link = next(i for i in listing.items if isinstance(i, Link))
    assert link.name == "avhrr-3"
    assert link._type is ItemType.LINK
    assert link.last_modified is None


def test_bare_string_location_structures():
    """CEDA sometimes returns location as a bare string, not a list."""
    listing = converter.structure(json.loads(FIXTURE.read_text()), Listing)
    pdc = next(
        f for f in listing.files if f.name == "00README" and f.directory == Path("/pdc")
    )
    assert pdc.location == [Location.DISK]
    assert pdc.on_disk is True


def test_file_roundtrip(real_listing):
    original = next(
        f
        for f in converter.structure(real_listing, Listing).files
        if f.name == "00README" and f.directory == Path("/neodc")
    )
    assert converter.structure(converter.unstructure(original), File) == original


def test_dual_location_file():
    data = {
        "path": "/x/dual.nc",
        "name": "dual.nc",
        "type": "file",
        "location": ["on_disk", "on_tape"],
        "md5": "a" * 32,
        "size": 10,
        "download": "https://example.com/dual.nc",
        "last_modified": "2025-01-01T00:00:00",
    }
    assert converter.structure(data, File).on_disk is True


def test_tape_only_file():
    data = {
        "path": "/x/tape.nc",
        "name": "tape.nc",
        "type": "file",
        "location": ["on_tape"],
        "md5": "a" * 32,
        "size": 10,
        "download": "https://example.com/tape.nc",
        "last_modified": "2025-01-01T00:00:00",
    }
    assert converter.structure(data, File).on_disk is False


def test_unknown_item_type_raises():
    with pytest.raises(Exception):  # noqa: B017
        converter.structure(
            {
                "path": "/x",
                "items": [
                    {
                        "path": "/x/mystery",
                        "name": "mystery",
                        "type": "unknown",
                        "last_modified": "2025-01-01T00:00:00",
                    }
                ],
            },
            Listing,
        )
