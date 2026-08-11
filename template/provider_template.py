"""Template DataProvider - copy this and implement registry() + run().

**MANDATORY**: This file demonstrates the fd-open-data-protocol requirement.
Every datasource package MUST expose a CATALOG dict conforming to DatasourceManifest schema.

Use this when you want to bundle catalog + fetch code in one class instead of
a YAML manifest. The class exposes ``CATALOG`` (loadable via ``load_catalog``)
and ``run()`` (the fetch runner).

**pyproject.toml entry-point** (required for auto-discovery):

    [project.entry-points."fd_open_data_mcp.datasources"]
    your-source = "your_package.catalog:CATALOG"
"""
from __future__ import annotations

from fd_open_data_protocol.provider import BaseDataProvider

# MANDATORY: CATALOG dict conforming to DatasourceManifest schema
# All fields below are required unless marked optional
CATALOG = {
    "version": "1",                                    # Required: protocol version
    "name": "<your-datasource-name>",                  # Required: unique identifier (kebab-case)
    "label": "<Human-readable label>",                 # Required: display name
    "source_url": "https://github.com/...",            # Optional: source repository URL
    "ranking_seed": [0.7, 0.7],                        # Optional: [quality, accessibility] scores
    "functions": [                                     # Required: list of function specs
        {
            "command": "<your_function>",              # Required: function name
            "category": "<category>",                  # Required: grouping category
            "description": "<what it returns>",        # Required: human-readable description
            "frequency": "<daily|yearly|...>",         # Required: data update frequency
            "parameters": [                            # Required: list of parameter specs
                {"name": "symbol", "type": "str", "required": True, "description": "Parameter description"}
            ],
            "columns": [                               # Required: list of column specs
                {"name": "<column>", "type": "float", "description": "<meaning>", "frequency": "daily"}
            ],
        }
    ],
    "concepts": [                                      # Optional: semantic mappings
        # {"column": "<col>", "concept": "<concept>", "entity_type": "<type>", "measure": "<measure>"}
    ],
    "entities": [                                      # Optional: entity coverage declarations
        # {"entity_type": "<type>", "coverage": "universe|explicit", "codes": [...]}
    ],
    "fetch": {"runner": "<your-datasource-name>"},     # Required: execution backend
    # OR: "fetch": {"module": "your_package.module:function"}
}


class YourProvider(BaseDataProvider):
    """DataProvider implementation for fd-open-data-protocol.

    This class wraps the CATALOG and provides the runtime fetch logic.
    """
    name = "<your-datasource-name>"

    def registry(self) -> dict:
        """Return the CATALOG for load_catalog() to consume."""
        return CATALOG

    def run(self, command: str, params: dict):
        """Execute a command and return results.

        Args:
            command: Function name from CATALOG["functions"]
            params: Parameters dict matching function's parameter spec

        Returns:
            Scalar value or pandas DataFrame with columns matching function's column spec
        """
        # Implement the upstream fetch here; return the value (scalar or DataFrame).
        raise NotImplementedError(f"run({command}) not implemented")
