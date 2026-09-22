import hashlib
import json
import threading
from base64 import b64encode
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
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
    TokenAuth.clear(USER)
    TokenAuth._cache[USER] = AccessToken(
        access_token=FAKE_TOKEN,
        expires=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    yield
    TokenAuth.clear(USER)


@pytest.fixture
def ceda_server():
    """A local HTTP server that mimics the CEDA data + token endpoints."""

    class Handler(BaseHTTPRequestHandler):
        files: dict[str, bytes] = {}
        listing: dict = {}
        token_hits: list[int] = []

        def log_message(self, *args):
            pass

        def _send(self, code, body: bytes, ctype="application/octet-stream"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlparse(self.path).path
            if path.startswith("/files/"):
                name = path.removeprefix("/files/")
                if name in self.files:
                    self._send(200, self.files[name])
                else:
                    self._send(404, b"not found")
            elif path.startswith("/data/"):
                self._send(200, json.dumps(self.listing).encode(), "application/json")
            else:
                self._send(404, b"not found")

        def do_POST(self):
            path = urlparse(self.path).path
            if path == "/token":
                self.token_hits.append(1)
                expected = "Basic " + b64encode(f"{USER}:{PASS}".encode()).decode()
                if self.headers.get("Authorization") != expected:
                    self._send(401, b"unauthorized", "application/json")
                    return
                body = json.dumps(
                    {
                        "access_token": FAKE_TOKEN,
                        "expires": (
                            datetime.now(timezone.utc) + timedelta(hours=1)
                        ).isoformat(),
                    }
                ).encode()
                self._send(200, body, "application/json")
            else:
                self._send(404, b"not found")

    files = {
        "alpha.nc": b"alpha-bytes",
        "beta.nc": b"beta-bytes",
        "gamma.txt": b"gamma",
        # listing claims a different md5 than the served content
        "corrupt.nc": b"corrupt-content",
    }
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
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

    Handler.files = files
    Handler.listing = {"path": f"/{DATA_DIR}", "items": items}

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield SimpleNamespace(url=f"{base}/", handler=Handler, files=files)
    httpd.shutdown()
    thread.join(timeout=5)


@pytest.fixture
def client(ceda_server, token_cache):
    return Client(USER, PASS, url=ceda_server.url)
