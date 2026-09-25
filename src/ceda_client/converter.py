"""Shared cattrs converter configured for the CEDA Archive's JSON format."""

from datetime import UTC, datetime
from typing import Any

import cattrs as cat
from cattrs.strategies import configure_tagged_union

from ceda_client.schema import Directory, File, Item, ItemType, Link
from ceda_client.token import AccessToken

__all__ = ["converter"]

converter = cat.Converter()


def _is_token(typ: Any) -> bool:
    """Whether ``typ`` is ``AccessToken`` or a subclass of it."""
    return isinstance(typ, type) and issubclass(typ, AccessToken)


def _is_item(typ: Any) -> bool:
    """Whether ``typ`` is ``Item`` or a subclass of it."""
    return isinstance(typ, type) and issubclass(typ, Item)


def _rename_overrides(typ: type) -> dict[str, Any]:
    """Build cattrs rename overrides from ``typ``'s ``_aliases`` mapping.

    ``_aliases`` maps Python attribute names to CEDA JSON keys, so
    structure/unstructure see and produce the JSON names.
    """
    return {name: cat.override(rename=key) for name, key in typ._aliases.items()}


@converter.register_structure_hook
def structure_datetime(value: str, typ: datetime) -> datetime:
    """Parse an ISO-8601 timestamp; CEDA sends naive timestamps in UTC."""
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


@converter.register_unstructure_hook
def unstructure_datetime(value: datetime) -> str:
    """Serialize a datetime to ISO-8601."""
    return value.isoformat()


@converter.register_structure_hook_factory(_is_token)
def structure_token_factory(typ: type, converter: cat.Converter):
    """Structure ``AccessToken`` from a dict with JSON-name aliases."""
    return cat.gen.make_dict_structure_fn(
        cl=typ, converter=converter, **_rename_overrides(typ)
    )


@converter.register_unstructure_hook_factory(_is_token)
def unstructure_token_factory(typ: type, converter: cat.Converter):
    """Unstructure ``AccessToken`` to a dict with JSON-name aliases."""
    return cat.gen.make_dict_unstructure_fn(
        cl=typ, converter=converter, **_rename_overrides(typ)
    )


def structure_location(value: Any, typ: type) -> Any:
    """Normalize ``location`` to a list; CEDA sometimes sends a bare string."""
    if isinstance(value, str):
        return [value]
    return value


@converter.register_structure_hook_factory(_is_item)
def _structure_item_factory(typ: type, conv: cat.Converter):
    """Structure item classes from dicts with aliases and location normalization."""
    return cat.gen.make_dict_structure_fn(
        cl=typ,
        converter=conv,
        location=cat.override(struct_hook=structure_location),
        **_rename_overrides(typ),
    )


@converter.register_unstructure_hook_factory(_is_item)
def unstructure_item_factory(typ: type, converter: cat.Converter):
    """Unstructure item classes to dicts with JSON-name aliases."""
    return cat.gen.make_dict_unstructure_fn(
        cl=typ, converter=converter, **_rename_overrides(typ)
    )


# Items form a tagged union: the JSON ``"type"`` field selects which class
# to structure into.
configure_tagged_union(
    Directory | File | Link,
    converter,
    tag_name="type",
    tag_generator={  # type: ignore[reportArgumentType]
        File: ItemType.FILE.value,
        Directory: ItemType.DIRECTORY.value,
        Link: ItemType.LINK.value,
    }.get,
)
