"""Template DataProvider - copy this and implement registry() + run().

Use this when you want to bundle catalog + fetch code in one class instead of
a YAML manifest. The class exposes ``CATALOG`` (loadable via ``load_catalog``)
and ``run()`` (the fetch runner).
"""
from __future__ import annotations

from fd_open_data_protocol.provider import BaseDataProvider

CATALOG = {
    "version": "1",
    "name": "<your-datasource-name>",
    "label": "<Human-readable label>",
    "functions": [
        {
            "command": "<your_function>",
            "category": "<category>",
            "description": "<what it returns>",
            "frequency": "<daily|yearly|...>",
            "parameters": [{"name": "symbol", "type": "str", "required": True}],
            "columns": [{"name": "<column>", "type": "float", "description": "<meaning>"}],
        }
    ],
    "concepts": [],
    "fetch": {"runner": "<your-datasource-name>"},
}


class YourProvider(BaseDataProvider):
    name = "<your-datasource-name>"

    def registry(self) -> dict:
        return CATALOG

    def run(self, command: str, params: dict):
        # Implement the upstream fetch here; return the value (scalar or DataFrame).
        raise NotImplementedError(f"run({command}) not implemented")
