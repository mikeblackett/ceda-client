# AGENTS.md

## Setup & commands

uv-managed, src layout, Python 3.14 (`.python-version`; supports >=3.12).
`uv sync` installs the package editable into `.venv`; run everything with
`uv run` from the repo root.

- The dev dependency group includes `ceda-client[dagster]`, so `uv sync`
  alone installs everything the test suite needs. In an install without the
  `dagster` extra, `tests/test_dagster_ceda.py` auto-skips via
  `pytest.importorskip`.
- `uv run pytest` — ~76 tests, ~20s, fully offline: `tests/conftest.py`
  runs a local `ThreadingHTTPServer` mimicking CEDA.
  Single test: `uv run pytest tests/test_client.py::test_name`.
- `uv run ruff check .` / `uv run ruff format --check .`
- `uv run pyright`
- `uv run coverage run -m pytest && uv run coverage report`

Keep all four green. RUF100 (unused noqa) is enforced alongside ruff's
default rules. CI (`.github/workflows/ci.yaml`) runs the same four checks on
push/PR to `main` and `dev` across Python 3.12–3.14; there is no pre-commit,
so local runs are still the first gate.

## Why this client exists

CEDA serves data over DAP2, which has no int64 type, so `pydap` can't fetch
int64 datasets. This client uses CEDA's JSON directory listings plus direct
HTTP downloads instead — don't "simplify" it back to a DAP2 client.

## Layout

- `src/ceda_client/` — the package (typed, `py.typed`); public API re-exported
  in `__init__.py`.
  - `client.py` — `Client`: listings, single/parallel downloads. Per-file
    failures never raise; they come back as `Status.FAILED` in
    `DownloadResult` / `ResultBatch`.
  - `schema.py` — frozen attrs models of CEDA JSON listings;
    `Directory | File | Link` is a cattrs tagged union keyed on JSON `"type"`.
  - `converter.py` — shared cattrs `converter`; JSON↔Python renames come from
    each model's `_aliases` ClassVar.
  - `auth.py` + `token.py` — bearer-token auth; tokens cached in the
    class-level `TokenAuth._cache` (keyed by username); 401s are retried once
    with a fresh token by `TokenAuthRetryAdapter`.
  - `integrations/dagster_ceda.py` — optional Dagster `ConfigurableResource`.
- `tests/` — pytest + hypothesis (shared strategies in `tests/strategies.py`);
  `tests/fixtures/real_listing.json` is a captured real CEDA listing.

## Gotchas

- CEDA JSON keys differ from Python attr names; the mapping lives in each
  model's `_aliases` (e.g. `download_url`↔`download`, `_type`↔`type`,
  `expires_at`↔`expires`). New fields need an alias entry; new item kinds
  need registration in the tagged union in `converter.py`.
- CEDA timestamps are naive UTC; the converter assumes naive → UTC.
- `File.md5` may be `""` (checksum check then skipped); `location` may be a
  bare string (normalized to a list); tape-only files (`on_tape`) raise
  `NotOnDiskError` on download.
- Downloads stream to a `.part` sibling and atomically rename; md5 uses
  `usedforsecurity=False`.
- `Client` normalizes `url` to a trailing slash (required for `urljoin`).
- Tests must never touch the network: seed/clear the token cache with the
  `token_cache` / `fresh_cache` / `stale_cache` fixtures from conftest.
- Branch workflow: develop on `dev`, merge to `main`
  (github.com/mikeblackett/ceda-client).
