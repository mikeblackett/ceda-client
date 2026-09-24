import hashlib
import json
import threading
from dataclasses import dataclass, field
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


@dataclass
class CedaServer:
    base: str
    valid_tokens: set[str] = field(default_factory=set)


@pytest.fixture
def ceda_server():
    """A local HTTP server that mimics the CEDA data endpoints."""

    class _Server(ThreadingHTTPServer):
        files: dict[str, bytes]
        listing: dict
        valid_tokens: set[str]

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
            token = self.headers.get("Authorization", "").removeprefix("Bearer ")
            if token not in server.valid_tokens:
                self._send(401, b"unauthorized", "text/plain")
                return
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
        "nomd5.dat": b"no-md5-bytes",
    }
    httpd = _Server(("127.0.0.1", 0), Handler)
    port = httpd.server_address[1]
    base = f"http://127.0.0.1:{port}"

    # md5 overrides per name: corrupt.nc claims a wrong checksum, nomd5.dat has none
    md5_overrides = {"corrupt.nc": _md5(b"something-else"), "nomd5.dat": ""}

    items = []
    for name, data in files.items():
        items.append(
            {
                "path": f"/{DATA_DIR}/{name}",
                "name": name,
                "type": "file",
                "location": ["on_disk"],
                "md5": md5_overrides.get(name, _md5(data)),
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
    # same basename as a file above, but from a different remote directory
    items.append(
        {
            "path": "/other-tree/alpha.nc",
            "name": "alpha.nc",
            "type": "file",
            "location": ["on_disk"],
            "md5": _md5(files["alpha.nc"]),
            "size": len(files["alpha.nc"]),
            "download": f"{base}/files/alpha.nc",
            "last_modified": "2025-01-01T00:00:00",
        }
    )

    httpd.files = files
    httpd.listing = {"path": f"/{DATA_DIR}", "items": items}
    valid_tokens: set[str] = {FAKE_TOKEN}
    httpd.valid_tokens = valid_tokens

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield CedaServer(base=f"{base}/", valid_tokens=valid_tokens)
    httpd.shutdown()
    thread.join(timeout=5)


@pytest.fixture
def client(ceda_server, token_cache):
    return Client(USER, PASS, url=ceda_server.base)
