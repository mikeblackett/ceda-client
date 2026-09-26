import pytest
from pydantic import ValidationError

dg = pytest.importorskip("dagster")

from ceda_client.client import (  # noqa: E402
    CEDA_ENDPOINT_URL,
    DEFAULT_WORKERS,
    Client,
    Status,
)
from ceda_client.integrations import DagsterCEDAResource  # noqa: E402

from .conftest import DATA_DIR, PASS, USER  # noqa: E402


def test_required_config():
    with pytest.raises(ValidationError):
        DagsterCEDAResource(username=USER)  # pyright: ignore[reportCallIssue]
    resource = DagsterCEDAResource(username=USER, password=PASS)
    assert resource.username == USER
    assert resource.url == CEDA_ENDPOINT_URL
    assert resource.max_workers == DEFAULT_WORKERS


def test_get_client_applies_config(mocker):
    resource = DagsterCEDAResource(
        username=USER,
        password=PASS,
        url="http://example.com",
        max_workers=4,
    )
    close = mocker.spy(Client, "close")
    with resource.get_client() as client:
        assert client.username == USER
        assert client.url == "http://example.com/"
        assert client.max_workers == 4
    close.assert_called_once()


def test_download_in_job(ceda_server, token_cache, tmp_path):
    resource = DagsterCEDAResource(
        username=USER,
        password=PASS,
        url=ceda_server.base,
    )

    @dg.op
    def download_alpha(ceda: DagsterCEDAResource) -> None:
        with ceda.get_client() as client:
            file = client.get_files(DATA_DIR, pattern="^alpha")[0]
            result = client.download(file, tmp_path)
            assert result.status is Status.SUCCESS

    @dg.job
    def job():
        download_alpha()

    result = job.execute_in_process(resources={"ceda": resource})
    assert result.success
    assert (tmp_path / "alpha.nc").read_bytes() == b"alpha-bytes"
