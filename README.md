# fd-open-data-protocol

**English** | [中文](README.zh-CN.md)

The **open-data datasource protocol**: a manifest contract a datasource exposes
(datasource + functions + columns + concept hints + fetch reference) so that
`fd-open-data-mcp` - or any consumer - can ingest it via `register_datasource`.

**Ship one manifest file -> the datasource is added. No consumer-side wiring.**

## One-click install

This library is a dependency of `fd-open-data-mcp` (pulled in transitively). To
install the **entire** finddata stack (hub + every datasource + ontology DB):

```bash
pip install "fd-open-data-mcp[data]" fd-polygon fd-cn-report

fd-open-data-mcp migrate \
  && fd-open-data-mcp import-catalog \
  && fd-open-data-mcp consume-concepts \
  && fd-open-data-mcp propose-bindings \
  && fd-open-data-mcp seed-entities \
  && fd-open-data-mcp generate-schedules \
  && fd-open-data-mcp register-discovered

fd-open-data-mcp serve
```

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

- **`DatasourceManifest`**: name, label, source_url, scanner_mode, ranking_seed, functions[], concepts[], entities[], entity_definitions[], relationships[], fetch.
- **`FunctionSpec`**: command, category, description, parameters[], columns[], frequency, verified.
- **`ColumnSpec`**: name, type, description, meaning, semantic_type, `frequency` + `datasource` (column-level).
- **`ConceptHint`**: column, concept, `entity_type`, `measure`, unit, frequency, confidence.
- **`EntitySpec`**: entity_type, coverage ("universe"|"explicit"), codes[] (for explicit coverage).
- **`Entity`**: entity_type, code, name_en, name_zh, metadata{}, relationships[].
- **`EntityRelationship`**: target_entity_type, target_code, relation_type, confidence, metadata{}.
- **`RelationshipSpec`**: relation_type, source_entity_type, target_entity_type, resolver_module.
- **`FetchRef`**: runner (built-in name) | module (`"pkg.mod:func"`).

`measure` + `entity_type` are **concept-level** (disambiguate GDP-nominal vs
GDP-PPP; stock close vs fund NAV). Column-level `frequency`/`datasource` support
composite functions whose columns come from different sources at different cadences.

## Entity Definitions

The protocol supports two ways to declare entities:

### 1. Coverage Declaration (`entities[]`)

Declares which entity types the datasource covers:

```yaml
entities:
  - entity_type: stock
    coverage: explicit
    codes: [AAPL, MSFT, GOOGL]
```

- `coverage: "universe"` - datasource can fetch data for all entities of this type
- `coverage: "explicit"` - datasource only covers the listed codes

### 2. Entity Metadata (`entity_definitions[]`)

Defines canonical entity metadata (names, attributes, relationships):

```yaml
entity_definitions:
  - entity_type: stock
    code: AAPL
    name_en: Apple Inc.
    name_zh: 苹果公司
    metadata:
      exchange: NASDAQ
      sector: Technology
    relationships:
      - target_entity_type: industry
        target_code: gics_10
        relation_type: belongs_to
```

When included, entities are registered in the ontology database during `register_datasource()`.

### Canonical Entity Types

All `entity_type` values must be from this vocabulary:

| Type | Description | Example IDs |
|------|-------------|-------------|
| `country` | ISO codes | CN, US, JP |
| `city` | Municipalities | beijing, shanghai |
| `stock` | A-shares | 600000.SH, 000001.SZ |
| `fund` | ETFs/funds | etf_code, fund_code |
| `bond` | Bonds | bond_code |
| `index` | Indices | SH000001, SZ399001 |
| `future` | Futures | cu2412, rb2401 |
| `crypto` | Cryptocurrencies | btc, eth |
| `organization` | General orgs | org_code |
| `industry` | Classifications | shenwan_1_01, gics_10 |
| `company` | Public companies | AAPL, TSLA |

## Manifest Declaration Requirement

**Every fd-* datasource package MUST declare a `DatasourceManifest` via one of the following mechanisms:**

1. **Python module**: Expose a `CATALOG` dict in a module (e.g., `catalog.py`) that conforms to the `DatasourceManifest` schema
2. **YAML/JSON file**: Place a manifest file at the package root (e.g., `catalog.yaml` or `catalog.json`)
3. **Entry-point declaration**: Register the manifest path in `pyproject.toml` under `[project.entry-points."fd_open_data_mcp.datasources"]`

The declaration **SHALL** be discoverable by `fd-open-data-mcp`'s auto-discovery mechanism (`register-discovered` command). Packages without a CATALOG declaration **SHALL NOT** be considered compliant with the fd-open-data-protocol.

### Recommended Package Structure

```
my-datasource/
├── pyproject.toml          # declares entry-point
└── my_pkg/
    ├── __init__.py
    └── catalog.py          # exposes CATALOG = { ... }
```

### Entry-Point Declaration

In your `pyproject.toml`:

```toml
[project.entry-points."fd_open_data_mcp.datasources"]
my-source = "my_pkg.catalog:CATALOG"
```

After `pip install my-pkg`, the package is automatically discoverable:

```bash
fd-open-data-mcp register-discovered
```

### Auto-Discovery Flow

1. **Install package** → `pip install my-datasource`
2. **Entry-point registered** → setuptools records `my-source = "my_pkg.catalog:CATALOG"`
3. **Auto-discover** → `fd-open-data-mcp register-discovered` scans all entry-points
4. **Load manifest** → `load_catalog()` validates and parses the CATALOG dict
5. **Register to ontology** → `register_datasource()` upserts sources/functions/columns/concepts

### Compliance Checklist

Before publishing a new datasource package, ensure:

- [ ] Package exposes a `CATALOG` dict or manifest file
- [ ] `pyproject.toml` declares entry-point under `fd_open_data_mcp.datasources` group
- [ ] CATALOG conforms to `DatasourceManifest` schema (version, name, label, functions[], concepts[], fetch)
- [ ] `load_catalog()` can successfully parse the manifest
- [ ] `fd-open-data-mcp register-discovered` discovers and registers the package

### Working Examples

- **fd-world**: `fd_world/catalog.py` + entry-point in `pyproject.toml`
- **fd-cn-gov**: `fd_cn_gov/catalog.py` + entry-point in `pyproject.toml`
- **fd-cn-report**: `catalog.py` + entry-point in `pyproject.toml`

## Template

Copy `template/datasource.template.yaml` (declarative) or
`template/provider_template.py` (a `BaseDataProvider` class with `run()`).
