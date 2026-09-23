import hashlib
import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast
from urllib.parse import urlparse

import pytest

from ceda_client.auth import AccessToken, TokenAuth
from ceda_client.client import Client

USER = "testuser"
PASS = "testpass"
FAKE_TOKEN = "fake-token-123"
DATA_DIR = "data/files"


def _md5(data: bytes) -> str:
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


@pytest.fixture
def token_cache():
    """Seed the class-level token cache so no network auth happens."""
    TokenAuth.clear()
    TokenAuth._cache[USER] = AccessToken(
        value=FAKE_TOKEN,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    yield
    TokenAuth.clear()


@pytest.fixture
def fresh_cache():
    TokenAuth.clear()
    TokenAuth._cache[USER] = AccessToken(
        value=FAKE_TOKEN,
        expires_at=datetime.now(UTC) + timedelta(days=3),
    )
    yield
    TokenAuth.clear()


@pytest.fixture
def stale_cache():
    TokenAuth.clear()
    TokenAuth._cache[USER] = AccessToken(
        value=FAKE_TOKEN,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    yield
    TokenAuth.clear()


@pytest.fixture
def ceda_server():
    """A local HTTP server that mimics the CEDA data endpoints."""

    class _Server(ThreadingHTTPServer):
        files: dict[str, bytes]
        listing: dict

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def _send(self, code, body: bytes, ctype="application/octet-stream"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            server = cast(_Server, self.server)
            path = urlparse(self.path).path
            if path.startswith("/files/"):
                name = path.removeprefix("/files/")
                if name in server.files:
                    self._send(200, server.files[name])
                else:
                    self._send(404, b"not found")
            elif path.startswith("/data/"):
                self._send(200, json.dumps(server.listing).encode(), "application/json")
            else:
                self._send(404, b"not found")

    files = {
        "alpha.nc": b"alpha-bytes",
        "beta.nc": b"beta-bytes",
        "gamma.txt": b"gamma",
        # listing claims a different md5 than the served content
        "corrupt.nc": b"corrupt-content",
    }
    httpd = _Server(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    base = f"http://127.0.0.1:{port}"

    items = []
    for name, data in files.items():
        items.append(
            {
                "path": f"/{DATA_DIR}/{name}",
                "name": name,
                "type": "file",
                "location": ["on_disk"],
                "md5": _md5(b"something-else") if name == "corrupt.nc" else _md5(data),
                "size": len(data),
                "download": f"{base}/files/{name}",
                "last_modified": "2025-01-01T00:00:00",
            }
        )
    items.append(
        {
            "path": f"/{DATA_DIR}/sub",
            "name": "sub",
            "type": "dir",
            "location": [None],
            "last_modified": None,
        }
    )
    # listed but not served -> 404 on download
    items.append(
        {
            "path": f"/{DATA_DIR}/missing.nc",
            "name": "missing.nc",
            "type": "file",
            "location": ["on_disk"],
            "md5": _md5(b"ghost"),
            "size": 5,
            "download": f"{base}/files/missing.nc",
            "last_modified": "2025-01-01T00:00:00",
        }
    )

    httpd.files = files
    httpd.listing = {"path": f"/{DATA_DIR}", "items": items}

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"{base}/"
    httpd.shutdown()
    thread.join(timeout=5)


@pytest.fixture
def client(ceda_server, token_cache):
    return Client(USER, PASS, url=ceda_server)
