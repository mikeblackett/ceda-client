from importlib import import_module
from typing import Any

_INTEGRATION_EXPORTS = {
    "DagsterCEDAResource": "ceda_client.integrations.dagster"
}


def __getattr__(name: str) -> Any:
    module_name = _INTEGRATION_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    # cache so subsequent access is a plain attribute lookup
    # and name shows up in `dir()` or `vars()`.
    globals()[name] = value
    return value
