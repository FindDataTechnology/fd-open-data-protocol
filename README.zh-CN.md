# fd-open-data-protocol

[English](README.md) | **中文**

**开放数据源协议 (open-data datasource protocol)**：数据源对外暴露的清单契约
(datasource + functions + columns + concept 提示 + fetch 引用)，使
`fd-open-data-mcp` — 或任何消费者 — 能通过 `register_datasource` 将其接入。

**提交一个清单文件 -> 数据源即被接入。消费者侧无需任何接线。**

## 清单 (The manifest)

一个 YAML/JSON 文件（或暴露 `CATALOG` 的 Python 模块）：

```yaml
version: "1"
name: my-source
label: My Source
ranking_seed: [0.7, 0.7]            # [quality, accessibility] 启发式种子
functions:
  - command: get_data
    frequency: daily
    parameters: [{name: symbol, type: str, required: true}]
    columns:
      - {name: close, type: float, frequency: daily}
concepts:                           # column -> concept 提示 (measure/entity_type 在此)
  - {column: close, concept: price.close, entity_type: stock, unit: currency, frequency: daily}
fetch:
  runner: my-source                  # 内置 runner 名称，或 module: "pkg.mod:run"
```

参见 `examples/example_stock.yaml`（声明式）和 `examples/example_macro.py`
（一个带 `run()` 的 `DataProvider` 类）。

## 加载 + 校验

```python
from fd_open_data_protocol.loader import load_catalog
manifest = load_catalog("examples/example_stock.yaml")
print(manifest.name, len(manifest.functions))
```

`load_catalog` 接受 YAML/JSON 文件路径、暴露 `CATALOG` 的 `.py` 文件、
`"pkg.mod"` 模块路径，或一个 dict。

## 向 fd-open-data-mcp 注册

```bash
fd-open-data-mcp register-datasource examples/example_stock.yaml
```

或使用 MCP 工具 `register_datasource(path)`。

## 从其他项目发布数据源

在你的数据源包的 `pyproject.toml` 中：

```toml
[project.entry-points."fd_open_data_mcp.datasources"]
my-source = "my_pkg.catalog:CATALOG"
```

`pip install my-pkg` -> fd-open-data-mcp 在 `import_catalog` 时自动注册它。

## 模式 (Schema)

- **`DatasourceManifest`**：name, label, source_url, scanner_mode, ranking_seed, functions[], concepts[], entities[], entity_definitions[], relationships[], fetch。
- **`FunctionSpec`**：command, category, description, parameters[], columns[], frequency, verified。
- **`ColumnSpec`**：name, type, description, meaning, semantic_type, `frequency` + `datasource`（列级）。
- **`ConceptHint`**：column, concept, `entity_type`, `measure`, unit, frequency, confidence。
- **`EntitySpec`**：entity_type, coverage ("universe"|"explicit"), codes[]（用于 explicit 覆盖）。
- **`Entity`**：entity_type, code, name_en, name_zh, metadata{}, relationships[]。
- **`EntityRelationship`**：target_entity_type, target_code, relation_type, confidence, metadata{}。
- **`RelationshipSpec`**：relation_type, source_entity_type, target_entity_type, resolver_module。
- **`FetchRef`**：runner (内置名) | module (`"pkg.mod:func"`)。

`measure` + `entity_type` 是 **概念级** 的（消歧 GDP-nominal 与
GDP-PPP；股票收盘价与基金净值）。列级 `frequency`/`datasource` 支持那些
列来自不同源、不同节奏的复合函数。

## 实体定义 (Entity Definitions)

协议支持两种声明实体的方式：

### 1. 覆盖声明 (`entities[]`)

声明数据源覆盖哪些实体类型：

```yaml
entities:
  - entity_type: stock
    coverage: explicit
    codes: [AAPL, MSFT, GOOGL]
```

- `coverage: "universe"` — 数据源可为该类型的所有实体取数
- `coverage: "explicit"` — 数据源只覆盖所列 codes

### 2. 实体元数据 (`entity_definitions[]`)

定义规范实体元数据（名称、属性、关系）：

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

包含时，实体在 `register_datasource()` 期间被注册进本体数据库。

### 规范实体类型 (Canonical Entity Types)

所有 `entity_type` 取值必须来自此词表：

| 类型 | 说明 | 示例 ID |
|------|------|---------|
| `country` | ISO 代码 | CN, US, JP |
| `city` | 城市 | beijing, shanghai |
| `stock` | A 股 | 600000.SH, 000001.SZ |
| `fund` | ETF/基金 | etf_code, fund_code |
| `bond` | 债券 | bond_code |
| `index` | 指数 | SH000001, SZ399001 |
| `future` | 期货 | cu2412, rb2401 |
| `crypto` | 加密货币 | btc, eth |
| `organization` | 一般组织 | org_code |
| `industry` | 行业分类 | shenwan_1_01, gics_10 |
| `company` | 上市公司 | AAPL, TSLA |

## 清单声明要求 (Manifest Declaration Requirement)

**每个 fd-* 数据源包必须通过以下机制之一声明一个 `DatasourceManifest`：**

1. **Python 模块**：在模块（如 `catalog.py`）中暴露一个符合 `DatasourceManifest`
   模式的 `CATALOG` dict
2. **YAML/JSON 文件**：在包根放置清单文件（如 `catalog.yaml` 或 `catalog.json`）
3. **entry-point 声明**：在 `pyproject.toml` 的
   `[project.entry-points."fd_open_data_mcp.datasources"]` 下注册清单路径

该声明**应 (SHALL)** 能被 `fd-open-data-mcp` 的自动发现机制
(`register-discovered` 命令) 发现。未声明 CATALOG 的包**不应 (SHALL NOT)**
被视为符合 fd-open-data-protocol。

### 推荐包结构

```
my-datasource/
├── pyproject.toml          # 声明 entry-point
└── my_pkg/
    ├── __init__.py
    └── catalog.py          # 暴露 CATALOG = { ... }
```

### Entry-Point 声明

在你的 `pyproject.toml` 中：

```toml
[project.entry-points."fd_open_data_mcp.datasources"]
my-source = "my_pkg.catalog:CATALOG"
```

`pip install my-pkg` 后，该包即被自动发现：

```bash
fd-open-data-mcp register-discovered
```

### 自动发现流程

1. **安装包** → `pip install my-datasource`
2. **entry-point 注册** → setuptools 记录 `my-source = "my_pkg.catalog:CATALOG"`
3. **自动发现** → `fd-open-data-mcp register-discovered` 扫描所有 entry-point
4. **加载清单** → `load_catalog()` 校验并解析 CATALOG dict
5. **注册进本体** → `register_datasource()` upsert sources/functions/columns/concepts

### 合规检查清单

发布新数据源包前，确保：

- [ ] 包暴露 `CATALOG` dict 或清单文件
- [ ] `pyproject.toml` 在 `fd_open_data_mcp.datasources` 组下声明 entry-point
- [ ] CATALOG 符合 `DatasourceManifest` 模式 (version, name, label, functions[], concepts[], fetch)
- [ ] `load_catalog()` 能成功解析清单
- [ ] `fd-open-data-mcp register-discovered` 能发现并注册该包

### 可用示例

- **fd-world**：`fd_world/catalog.py` + `pyproject.toml` 中的 entry-point
- **fd-cn-gov**：`fd_cn_gov/catalog.py` + `pyproject.toml` 中的 entry-point
- **fd-cn-report**：`catalog.py` + `pyproject.toml` 中的 entry-point

## 模板 (Template)

复制 `template/datasource.template.yaml`（声明式）或
`template/provider_template.py`（一个带 `run()` 的 `BaseDataProvider` 类）。
