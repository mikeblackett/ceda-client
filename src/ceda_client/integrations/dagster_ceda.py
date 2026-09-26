"""Dagster integration: a ConfigurableResource wrapping the CEDA client."""

import dagster as dg

from ceda_client.client import (
    CEDA_ENDPOINT_URL,
    DEFAULT_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_READ_TIMEOUT_SECONDS,
    DEFAULT_WORKERS,
    Client,
)


class DagsterCEDAResource(dg.ConfigurableResource):
    """Dagster resource that creates CEDA ``Client`` instances.

    Use :meth:`get_client` as a context manager inside ops and assets:

    .. code-block:: python

        @dg.asset
        def my_asset(ceda: DagsterCEDAResource):
            with ceda.get_client() as client:
                files = client.get_files("/data/some/dir", extension=".nc")
                client.download_multi(files, target)
    """

    username: str
    password: str
    url: str = CEDA_ENDPOINT_URL
    max_workers: int = DEFAULT_WORKERS
    connect_timeout: float | None = DEFAULT_CONNECT_TIMEOUT_SECONDS
    read_timeout: float | None = DEFAULT_READ_TIMEOUT_SECONDS

    def get_client(self) -> Client:
        """Create a CEDA client from this resource's config.

        Use it as a context manager so the HTTP session is closed after use.
        """
        return Client(
            self.username,
            self.password,
            url=self.url,
            max_workers=self.max_workers,
            connect_timeout=self.connect_timeout,
            read_timeout=self.read_timeout,
        )
