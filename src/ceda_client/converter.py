from datetime import datetime
from typing import Any

import cattrs as cat
from cattrs.strategies import configure_tagged_union

from ceda_client.schema import Directory, File, Item, ItemType, Link
from ceda_client.token import AccessToken

__all__ = ["converter"]

converter = cat.Converter()


def _is_token(typ: Any) -> bool:
    return isinstance(typ, type) and issubclass(typ, AccessToken)


def _is_item(typ: Any) -> bool:
    return isinstance(typ, type) and issubclass(typ, Item)


def _rename_overrides(typ: type) -> dict[str, Any]:
    return {name: cat.override(rename=key) for name, key in typ._aliases.items()}


@converter.register_structure_hook
def structure_datetime(value: str, typ: datetime) -> datetime:
    return datetime.fromisoformat(value)


@converter.register_unstructure_hook
def unstructure_datetime(value: datetime) -> str:
    return value.isoformat()


@converter.register_structure_hook_factory(_is_token)
def structure_token_factory(typ: type, converter: cat.Converter):
    return cat.gen.make_dict_structure_fn(
        cl=typ, converter=converter, **_rename_overrides(typ)
    )


@converter.register_unstructure_hook_factory(_is_token)
def unstructure_token_factory(typ: type, converter: cat.Converter):
    return cat.gen.make_dict_unstructure_fn(
        cl=typ, converter=converter, **_rename_overrides(typ)
    )


def structure_location(value: Any, _) -> Any:
    # CEDA sometimes sends location as a bare string rather than a list
    if isinstance(value, str):
        return [value]
    return value


@converter.register_structure_hook_factory(_is_item)
def _structure_item_factory(typ: type, conv: cat.Converter):
    return cat.gen.make_dict_structure_fn(
        cl=typ,
        converter=conv,
        location=cat.override(struct_hook=structure_location),
        **_rename_overrides(typ),
    )


@converter.register_unstructure_hook_factory(_is_item)
def unstructure_item_factory(typ: type, converter: cat.Converter):
    return cat.gen.make_dict_unstructure_fn(
        cl=typ, converter=converter, **_rename_overrides(typ)
    )


configure_tagged_union(
    Directory | File | Link,
    converter,
    tag_name="type",
    tag_generator={  # type: ignore[reportArgumentType]
        File: ItemType.FILE.value,
        Directory: ItemType.DIR.value,
        Link: ItemType.LINK.value,
    }.get,
)
