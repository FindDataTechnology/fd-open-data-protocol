"""Example macro datasource implementing the DataProvider interface (Python).

A datasource that prefers to bundle catalog + fetch code: define a ``CATALOG``
dict (loadable via ``load_catalog``) and a ``BaseDataProvider`` subclass with
``run()``. ``load_catalog("examples.example_macro")`` or
``load_catalog("examples/example_macro.py")`` both return the manifest.
"""
from __future__ import annotations

from fd_open_data_protocol.provider import BaseDataProvider

CATALOG = {
    "version": "1",
    "name": "example-macro",
    "label": "Example Macro Datasource",
    "source_url": "https://example.com/macro",
    "ranking_seed": [0.9, 0.8],
    "functions": [
        {
            "command": "get_gdp",
            "category": "macro",
            "description": "GDP (current US$) for a country + year",
            "frequency": "yearly",
            "parameters": [{"name": "economy", "type": "str", "required": True}],
            "columns": [
                {"name": "NY.GDP.MKTP.CD", "type": "float", "description": "GDP (current US$)"},
            ],
        }
    ],
    "concepts": [
        # measure disambiguates GDP variants (nominal_current vs real vs ppp)
        {"column": "NY.GDP.MKTP.CD", "concept": "gdp", "entity_type": "country",
         "measure": "nominal_current", "unit": "usd", "frequency": "yearly"},
    ],
    "fetch": {"runner": "example-macro"},
}


class ExampleMacroProvider(BaseDataProvider):
    name = "example-macro"

    def registry(self) -> dict:
        return CATALOG

    def run(self, command: str, params: dict):
        # In a real provider, call the upstream API here and return the value.
        raise NotImplementedError(f"example run({command}) not implemented")
