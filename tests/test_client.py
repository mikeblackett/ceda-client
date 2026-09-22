from pathlib import Path

import pytest
import upath as up

from ceda_client.client import SkipPolicy, Status

from .conftest import DATA_DIR


def test_resolve_url(client):
    base = client.url.rstrip("/")
    assert client.resolve_url("data/files") == f"{base}/data/files"
    assert client.resolve_url("/data/files") == f"{base}/data/files"


def test_get_listing(client):
    listing = client.get_listing(DATA_DIR)
    names = {i.name for i in listing.items}
    assert names == {"alpha.nc", "beta.nc", "gamma.txt", "corrupt.nc", "sub", "missing.nc"}
    assert len(listing.files) == 5
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
    assert [f.name for f in files] == ["alpha.nc"]


def test_download_success(client, tmp_path):
    file = client.get_files(DATA_DIR, pattern="^alpha")[0]
    result = client.download(file, tmp_path)
    assert result.status is Status.SUCCESS
    assert result.path.read_bytes() == b"alpha-bytes"
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
    assert isinstance(result.error, Exception)
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


def test_download_multi_all_success(client, tmp_path):
    files = client.get_files(DATA_DIR, pattern=r"^(alpha|beta|gamma)")
    batch = client.download_multi(files, tmp_path)
    assert dict(batch.counter) == {Status.SUCCESS: 3}
    assert len(batch.success) == 3
    assert batch.failed == []
    assert batch.skipped == []
    assert (tmp_path / "alpha.nc").read_bytes() == b"alpha-bytes"
    assert (tmp_path / "beta.nc").read_bytes() == b"beta-bytes"
    assert (tmp_path / "gamma.txt").read_bytes() == b"gamma"


def test_download_multi_mixed_results(client, tmp_path):
    files = client.get_files(DATA_DIR, pattern=r"^(alpha|corrupt|missing)")
    batch = client.download_multi(files, tmp_path)
    assert batch.counter[Status.SUCCESS] == 1
    assert batch.counter[Status.FAILED] == 2
    assert {r.file.name for r in batch.failed} == {"corrupt.nc", "missing.nc"}
    assert (tmp_path / "alpha.nc").read_bytes() == b"alpha-bytes"


def test_download_multi_skips_existing(client, tmp_path):
    (tmp_path / "alpha.nc").write_bytes(b"alpha-bytes")
    files = client.get_files(DATA_DIR, pattern=r"^(alpha|beta)")
    batch = client.download_multi(files, tmp_path)
    assert batch.counter[Status.SUCCESS] == 1
    assert batch.counter[Status.SKIPPED] == 1
    assert batch.skipped[0].file.name == "alpha.nc"


def test_download_multi_empty(client, tmp_path):
    batch = client.download_multi([], tmp_path)
    assert batch.results == ()
    assert batch.counter == {}


def test_client_context_manager_closes_session(client):
    _ = client.session  # force creation
    with client:
        assert client.session is not None
    assert client._session is None
