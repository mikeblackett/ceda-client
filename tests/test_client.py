from datetime import UTC, datetime, timedelta

import pytest
import requests as rq
from pytest_mock import MockerFixture

from ceda_client.auth import AccessToken, TokenAuth
from ceda_client.client import Client, SkipPolicy, Status
from ceda_client.converter import converter
from ceda_client.schema import File

from .conftest import DATA_DIR, FAKE_TOKEN, PASS, USER


def test_resolve_url(client):
    base = client.url.rstrip("/")
    assert client.resolve_url("data/files") == f"{base}/data/files"
    assert client.resolve_url("/data/files") == f"{base}/data/files"


def _file(name: str, path: str, location: list[str] | None = None) -> File:
    return converter.structure(
        {
            "path": path,
            "name": name,
            "type": "file",
            "location": location or ["on_disk"],
            "md5": "a" * 32,
            "size": 1,
            "download": f"https://example.com/{path}",
            "last_modified": None,
        },
        File,
    )


def test_base_url_path_is_preserved():
    c = Client(USER, PASS, url="http://h/proxy")
    try:
        assert c.url == "http://h/proxy/"
        assert c.resolve_url("data/files") == "http://h/proxy/data/files"
    finally:
        c.close()


def test_get_listing(client):
    listing = client.get_listing(DATA_DIR)
    names = {i.name for i in listing.items}
    assert names == {
        "alpha.nc",
        "beta.nc",
        "gamma.txt",
        "corrupt.nc",
        "sub",
        "missing.nc",
        "nomd5.dat",
    }
    assert len(listing.files) == 7
    assert len(listing.directories) == 1


def test_get_files_extension_filter(client):
    files = client.get_files(DATA_DIR, extension=".nc")
    assert {f.name for f in files} == {
        "alpha.nc",
        "beta.nc",
        "corrupt.nc",
        "missing.nc",
    }


def test_get_files_pattern_filter(client):
    files = client.get_files(DATA_DIR, pattern=r"^(alpha|gamma)")
    assert {f.name for f in files} == {"alpha.nc", "gamma.txt"}


def test_get_files_combined_filters(client):
    files = client.get_files(DATA_DIR, extension=".nc", pattern="^a")
    assert {f.name for f in files} == {"alpha.nc"}


def test_get_json_listing_error_propagates(client):
    with pytest.raises(rq.HTTPError) as excinfo:
        client.get_json_listing("does-not-exist")
    assert excinfo.value.response is not None
    assert excinfo.value.response.status_code == 404


def test_download_success(client, tmp_path):
    file = client.get_files(DATA_DIR, pattern="^alpha")[0]
    result = client.download(file, tmp_path)
    assert result.status is Status.SUCCESS
    assert result.target.read_bytes() == b"alpha-bytes"
    assert not (tmp_path / "alpha.nc.part").exists()


def test_download_creates_nested_target(client, tmp_path):
    file = client.get_files(DATA_DIR, pattern="^alpha")[0]
    target = tmp_path / "a" / "b"
    result = client.download(file, target)
    assert result.status is Status.SUCCESS
    assert (target / "alpha.nc").read_bytes() == b"alpha-bytes"


def test_download_checksum_mismatch_fails(client, tmp_path):
    file = client.get_files(DATA_DIR, pattern="^corrupt")[0]
    result = client.download(file, tmp_path)
    assert result.status is Status.FAILED
    assert isinstance(result.error, ValueError)
    assert not (tmp_path / "corrupt.nc").exists()
    assert not (tmp_path / "corrupt.nc.part").exists()


def test_download_http_error_fails(client, tmp_path):
    file = client.get_files(DATA_DIR, pattern="^missing")[0]
    result = client.download(file, tmp_path)
    assert result.status is Status.FAILED
    assert isinstance(result.error, rq.HTTPError)
    assert not (tmp_path / "missing.nc").exists()


def test_skip_exists(client, tmp_path):
    (tmp_path / "alpha.nc").write_bytes(b"whatever, wrong size")
    file = client.get_files(DATA_DIR, pattern="^alpha")[0]
    result = client.download(file, tmp_path, skip_policy=SkipPolicy.EXISTS)
    assert result.status is Status.SKIPPED
    assert (tmp_path / "alpha.nc").read_bytes() == b"whatever, wrong size"


def test_skip_size_match(client, tmp_path):
    (tmp_path / "alpha.nc").write_bytes(b"X" * 11)  # same size, different content
    file = client.get_files(DATA_DIR, pattern="^alpha")[0]
    result = client.download(file, tmp_path, skip_policy=SkipPolicy.SIZE)
    assert result.status is Status.SKIPPED


def test_skip_size_mismatch_redownloads(client, tmp_path):
    (tmp_path / "alpha.nc").write_bytes(b"X" * 10)
    file = client.get_files(DATA_DIR, pattern="^alpha")[0]
    result = client.download(file, tmp_path, skip_policy=SkipPolicy.SIZE)
    assert result.status is Status.SUCCESS
    assert (tmp_path / "alpha.nc").read_bytes() == b"alpha-bytes"


def test_skip_checksum_match(client, tmp_path):
    (tmp_path / "alpha.nc").write_bytes(b"alpha-bytes")
    file = client.get_files(DATA_DIR, pattern="^alpha")[0]
    result = client.download(file, tmp_path, skip_policy=SkipPolicy.CHECKSUM)
    assert result.status is Status.SKIPPED


def test_skip_checksum_mismatch_redownloads(client, tmp_path):
    (tmp_path / "alpha.nc").write_bytes(b"X" * 11)  # same size, wrong md5
    file = client.get_files(DATA_DIR, pattern="^alpha")[0]
    result = client.download(file, tmp_path, skip_policy=SkipPolicy.CHECKSUM)
    assert result.status is Status.SUCCESS
    assert (tmp_path / "alpha.nc").read_bytes() == b"alpha-bytes"


def test_skip_checksum_missing_file_redownloads(client, tmp_path):
    file = client.get_files(DATA_DIR, pattern="^alpha")[0]
    result = client.download(file, tmp_path, skip_policy=SkipPolicy.CHECKSUM)
    assert result.status is Status.SUCCESS


def test_overwrite_always_redownloads(client, tmp_path):
    (tmp_path / "alpha.nc").write_bytes(b"alpha-bytes")
    file = client.get_files(DATA_DIR, pattern="^alpha")[0]
    result = client.download(file, tmp_path, skip_policy=SkipPolicy.OVERWRITE)
    assert result.status is Status.SUCCESS


def test_download_target_is_file_raises(client, tmp_path):
    target = tmp_path / "notadir"
    target.write_bytes(b"x")
    file = client.get_files(DATA_DIR, pattern="^alpha")[0]
    with pytest.raises(NotADirectoryError):
        client.download(file, target)


def test_download_tape_only_raises(client, tmp_path):
    file = _file("tape.nc", "/x/tape.nc", location=["on_tape"])
    with pytest.raises(ValueError, match="on disk"):
        client.download(file, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_download_multi_all_success(client, tmp_path):
    files = client.get_files(DATA_DIR, pattern=r"^(beta|gamma)")
    batch = client.download_multi(files, tmp_path)
    assert dict(batch.counter) == {Status.SUCCESS: 2}
    assert len(batch.success) == 2
    assert batch.failed == []
    assert batch.skipped == []
    assert (tmp_path / "beta.nc").read_bytes() == b"beta-bytes"
    assert (tmp_path / "gamma.txt").read_bytes() == b"gamma"


def test_download_multi_mixed_results(client, tmp_path):
    files = client.get_files(DATA_DIR, pattern=r"^(beta|corrupt|missing)")
    batch = client.download_multi(files, tmp_path)
    assert batch.counter[Status.SUCCESS] == 1
    assert batch.counter[Status.FAILED] == 2
    assert {r.file.name for r in batch.failed} == {"corrupt.nc", "missing.nc"}
    assert (tmp_path / "beta.nc").read_bytes() == b"beta-bytes"


def test_download_multi_skips_existing(client, tmp_path):
    (tmp_path / "beta.nc").write_bytes(b"beta-bytes")
    files = client.get_files(DATA_DIR, pattern=r"^(beta|gamma)")
    batch = client.download_multi(files, tmp_path)
    assert batch.counter[Status.SUCCESS] == 1
    assert batch.counter[Status.SKIPPED] == 1
    assert batch.skipped[0].file.name == "beta.nc"


def test_download_multi_empty(client, tmp_path):
    batch = client.download_multi([], tmp_path)
    assert batch.results == ()
    assert batch.counter == {}


def test_download_empty_md5_skips_verification(client, tmp_path):
    file = client.get_files(DATA_DIR, pattern="^nomd5")[0]
    result = client.download(file, tmp_path)
    assert result.status is Status.SUCCESS
    assert result.target.read_bytes() == b"no-md5-bytes"


def test_download_mirror_dirs(client, tmp_path):
    file = client.get_files(DATA_DIR, pattern="^alpha")[0]
    assert str(file.path) == f"/{DATA_DIR}/alpha.nc"
    result = client.download(file, tmp_path, mirror_dirs=True)
    assert result.status is Status.SUCCESS
    expected = tmp_path / DATA_DIR / "alpha.nc"
    assert expected.read_bytes() == b"alpha-bytes"


def test_download_multi_duplicate_basenames_raise(client, tmp_path):
    for files in (
        [_file("x.nc", "/a/x.nc"), _file("x.nc", "/b/x.nc")],
        [_file("x.nc", "/a/x.nc"), _file("X.NC", "/b/X.NC")],
    ):
        with pytest.raises(ValueError, match="duplicate file names"):
            client.download_multi(files, tmp_path)
        assert list(tmp_path.iterdir()) == []


def test_download_multi_mirror_dirs(client, tmp_path):
    files = client.get_files(DATA_DIR, pattern="^alpha")
    assert {str(f.path) for f in files} == {
        f"/{DATA_DIR}/alpha.nc",
        "/other-tree/alpha.nc",
    }
    batch = client.download_multi(files, tmp_path, mirror_dirs=True)
    assert dict(batch.counter) == {Status.SUCCESS: 2}
    assert (tmp_path / DATA_DIR / "alpha.nc").read_bytes() == b"alpha-bytes"
    assert (tmp_path / "other-tree" / "alpha.nc").read_bytes() == b"alpha-bytes"


def test_client_reauths_on_401(client, ceda_server, mocker: MockerFixture):
    new_token = "reauth-token-xyz"
    ceda_server.valid_tokens.discard(FAKE_TOKEN)
    ceda_server.valid_tokens.add(new_token)
    mock = mocker.patch(
        "ceda_client.auth.TokenAuth._fetch",
        return_value=AccessToken(new_token, datetime.now(UTC) + timedelta(hours=1)),
    )

    listing = client.get_listing(DATA_DIR)

    assert len(listing.items) > 0
    mock.assert_called_once_with(USER, PASS)
    assert TokenAuth._cache[USER].value == new_token


def test_client_context_manager_closes_session(client):
    with client:
        assert client.session is not None
    assert client._session is None


def test_close_is_idempotent_and_session_recreated(client):
    client.close()
    client.close()
    session = client.session
    assert session is not None
    client.close()
