"""Provider-neutral Catalog models: the Eslite code and the list types that Kingstone re-exports."""

from __future__ import annotations

import catalog_core.models as catalog_models
import kingstone.models as kingstone_models
from catalog_core.models import ListedItem, ListPage, ProviderCode


def test_eslite_is_a_provider_code_with_its_stored_value():
    assert ProviderCode.ESLITE == "ESLITE"


def test_kingstone_models_re_export_the_catalog_list_types():
    assert kingstone_models.ListedItem is catalog_models.ListedItem
    assert kingstone_models.ListPage is catalog_models.ListPage
    assert kingstone_models.ListedItem is ListedItem
    assert kingstone_models.ListPage is ListPage


def test_kingstone_models_keep_its_own_errors():
    assert set(kingstone_models.__all__) >= {"ListedItem", "ListPage", "KingstoneParseError", "ProductNotFound"}
