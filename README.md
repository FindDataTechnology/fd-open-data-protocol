# fd-open-data-protocol

The **open-data datasource protocol**: a manifest contract a datasource exposes
(datasource + functions + columns + concept hints + fetch reference) so that
`fd-open-data-mcp` - or any consumer - can ingest it via `register_datasource`.

**Ship one manifest file -> the datasource is added. No consumer-side wiring.**

## The manifest

A YAML/JSON file (or a Python module exposing `CATALOG`):

```yaml
version: "1"
name: my-source
label: My Source
ranking_seed: [0.7, 0.7]            # [quality, accessibility] heuristic seed
functions:
  - command: get_data
    frequency: daily
    parameters: [{name: symbol, type: str, required: true}]
    columns:
      - {name: close, type: float, frequency: daily}
concepts:                           # column -> concept hints (measure/entity_type here)
  - {column: close, concept: price.close, entity_type: stock, unit: currency, frequency: daily}
fetch:
  runner: my-source                  # built-in runner name, OR module: "pkg.mod:run"
```

See `examples/example_stock.yaml` (declarative) and `examples/example_macro.py`
(a `DataProvider` class with `run()`).

## Load + validate

```python
from fd_open_data_protocol.loader import load_catalog
manifest = load_catalog("examples/example_stock.yaml")
print(manifest.name, len(manifest.functions))
```

`load_catalog` accepts a YAML/JSON file path, a `.py` file exposing `CATALOG`,
a `"pkg.mod"` module path, or a dict.

## Register with fd-open-data-mcp

```bash
fd-open-data-mcp register-datasource examples/example_stock.yaml
```

or the MCP tool `register_datasource(path)`.

## Publish a datasource from another project

In your datasource package's `pyproject.toml`:

```toml
[project.entry-points."fd_open_data_mcp.datasources"]
my-source = "my_pkg.catalog:CATALOG"
```

`pip install my-pkg` -> fd-open-data-mcp auto-registers it on `import_catalog`.

## Schema

- **`DatasourceManifest`**: name, label, source_url, scanner_mode, ranking_seed, functions[], concepts[], fetch.
- **`FunctionSpec`**: command, category, description, parameters[], columns[], frequency, verified.
- **`ColumnSpec`**: name, type, description, meaning, semantic_type, `frequency` + `datasource` (column-level).
- **`ConceptHint`**: column, concept, `entity_type`, `measure`, unit, frequency, confidence.
- **`FetchRef`**: runner (built-in name) | module (`"pkg.mod:func"`).

`measure` + `entity_type` are **concept-level** (disambiguate GDP-nominal vs
GDP-PPP; stock close vs fund NAV). Column-level `frequency`/`datasource` support
composite functions whose columns come from different sources at different cadences.

## Template

Copy `template/datasource.template.yaml` (declarative) or
`template/provider_template.py` (a `BaseDataProvider` class with `run()`).
