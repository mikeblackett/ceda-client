import pytest as pt

import ceda_client


def test_unknown_top_level_attribute_raises():
    with pt.raises(AttributeError, match="has no attribute"):
        _ = ceda_client.definitely_not_an_export
