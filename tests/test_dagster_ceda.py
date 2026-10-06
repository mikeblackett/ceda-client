import pytest as pt

from ceda_client.client import (
    CEDA_ENDPOINT_URL,
    DEFAULT_WORKERS,
    Client,
    Status,
)

from .conftest import DATA_DIR, PASSWORD, USERNAME

dg = pt.importorskip("dagster")
from pydantic import ValidationError

from ceda_client.integrations import DagsterCEDAResource


def test_required_config():
    with pt.raises(ValidationError):
        DagsterCEDAResource(username=USERNAME)  # pyright: ignore[reportCallIssue]
    resource = DagsterCEDAResource(username=USERNAME, password=PASSWORD)
    assert resource.username == USERNAME
    assert resource.url == CEDA_ENDPOINT_URL
    assert resource.max_workers == DEFAULT_WORKERS


def test_get_client_applies_config(mocker):
    url = "http://example.com"
    resource = DagsterCEDAResource(
        username=USERNAME,
        password=PASSWORD,
        url=url,
        max_workers=4,
    )
    close = mocker.spy(Client, "close")
    with resource.get_client() as client:
        assert client.username == USERNAME
        assert client.url == url
        assert client.max_workers == 4
    close.assert_called_once()


def test_download_in_job(ceda_server, fresh_token_cache, tmp_path):
    resource = DagsterCEDAResource(
        username=USERNAME,
        password=PASSWORD,
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
