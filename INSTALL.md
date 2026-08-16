# fd-open-data-protocol — install spec (agent-executable)

> You are an AI agent. A user handed you this file's raw URL. Follow it top to
> bottom. Run every command. Stop and report on the first real failure. This
> spec is idempotent: re-running is safe. Do not commit secrets.

## Goal

Install `fd-open-data-protocol` — the manifest contract that datasources expose
so `fd-open-data-mcp` (or any consumer) can ingest them.

## What is fd-open-data-protocol

- A Python library defining `DatasourceManifest`, `FunctionSpec`, `ColumnSpec`,
  `ConceptHint`, `Entity`, `EntityRelationship`, `FetchRef`, etc.
- A `load_catalog()` function that accepts YAML / JSON / Python `CATALOG` dict / dict
- **Pulled in transitively** by `fd-open-data-mcp` — you rarely need to install
  it alone

## Step 1 — Install

### Option A: as part of the full stack (recommended)

```bash
pip install "fd-open-data-mcp[data]" fd-polygon fd-cn-report
```

`fd-open-data-protocol` is a dependency of `fd-open-data-mcp` and is installed
automatically.

### Option B: standalone (for authoring manifests)

```bash
pip install fd-open-data-protocol
```

## Step 2 — Verify

```bash
python -c "
from fd_open_data_protocol.loader import load_catalog
from fd_open_data_protocol.schema import DatasourceManifest
print('protocol version:', DatasourceManifest.model_fields.keys() if hasattr(DatasourceManifest, 'model_fields') else 'OK')
print('load_catalog:', load_catalog)
"
```

Expected: imports succeed, `DatasourceManifest` fields printed.

## Step 3 — Author a manifest (optional)

Copy a template and fill it in:

```bash
# Declarative (YAML)
cp template/datasource.template.yaml my-source.yaml

# Or programmatic (Python)
cp template/provider_template.py my_source_catalog.py
```

Validate it:

```bash
python -c "
from fd_open_data_protocol.loader import load_catalog
m = load_catalog('my-source.yaml')   # or 'my_source_catalog.py'
print(f'{m.name}: {len(m.functions)} functions, {len(m.concepts)} concepts')
"
```

## Step 4 — Register with fd-open-data-mcp (if hub is installed)

```bash
fd-open-data-mcp register-datasource my-source.yaml
# or via entry-point:
fd-open-data-mcp register-discovered
```

## Failure modes

| Symptom | Cause |
|---------|-------|
| `ModuleNotFoundError: fd_open_data_protocol` | `pip install` didn't run |
| `load_catalog` raises validation error | manifest doesn't conform to `DatasourceManifest` schema |
| `register-datasource` fails | `fd-open-data-mcp` not installed, or DB path wrong |

## What to report back

- install exit code
- verification output
- manifest validation result (if authored one)
- registration result (if hub is installed)
