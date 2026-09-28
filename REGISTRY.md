# 统一指标注册目录（Unified Indicator Registry）

把任何数据库的指标行登记进一张统一目录表（`fd_open_data.registry_entries`），
带**原生码锚点 + 语义命名层 + 命名质量门**：

- **锚点**：`(source_db, source_table, source_column, native_code)` 唯一，幂等
  upsert 主键；原生码永不改写（`v176`、`23072` 这类码也原样保留）。
- **语义命名层**：`semantic_code`（AI 可读，`^[A-Za-z][A-Za-z0-9._-]*`）+
  双语名（`name_zh`/`name_en`）+ 元数据（`unit`/`frequency`/`domain`，
  允许 unknown）。
- **质量门**：命名要素缺任何一项 ⇒ `verified=false`，**不进任何公网目录面**
  （fd-open-data-mcp 目录工具、官网 /indicators）；但留在注册表内可审计。
  `verified` 记录核验方（`rule:naming-gate` 或人工 id）。命名变更会自动
  降级为 unverified，需重核。

## 新源接入配方（四步）

对齐宏观源接入配方（[[macro-crawl-recipe]] 思想）：

```
1. 适配器     cp template/registry_adapter.template.yaml <db>.yaml 并填写映射
2. 登记       register（全量 upsert，幂等；重跑=增量）
3. 绑定       跨源等价概念用既有 concept_bindings 语义绑定，不合并身份
4. verified   补齐命名（列直取 / literal / map_file 批量起草）→ verify → 抽样记录
```

### 1. 适配器（纯声明，不动核心代码）

一个源表一个 YAML：`source_db` / `source_table` / `native_code_column` +
`fields` 映射（三种取值：`column` 直取列、`literal` 常量、`map_file` JSON
`{native_code: value}` 批量起草——LLM 起草的译名/语义码就走这个）。
`provenance_columns` 把源行关键片段（label_cn、topic）快照进 provenance。
模板：`template/registry_adapter.template.yaml`；可跑示例：
`examples/registry_mini/`（无需数据库）。

### 2. 登记（幂等 + 增量）

```bash
export FD_REGISTRY_DSN='host=... user=fd_sync dbname=fd_open_data ...'
export FD_SOURCE_DSN='host=... user=... dbname=<源库> ...'

python -m fd_open_data_protocol.registry_cli init-db                 # 首次建表
python -m fd_open_data_protocol.registry_cli register \
    --adapter adapters/<db>.yaml --auto-verify                       # 全量
python -m fd_open_data_protocol.registry_cli register \
    --adapter adapters/<db>.yaml --auto-verify                       # 重跑=增量（unchanged 不动）
```

输出：`registered=<新> updated=<改> unchanged=<未变> demoted=<命名漂移降级>`。
源库无中文/英文名时，先用 `map_file` 补齐再登记，或先登记 unverified 挂账
（见下）。

### 3. 绑定

同义指标跨源等价（如镜像 `GDP_AMOUNT` ≡ WB `NY.GDP.MKTP.CD`）用目录既有
`concept_bindings` 语义做绑定；**不强行合并身份**（锚点各自保留）。

### 4. verified（规则 + 抽样）

```bash
python -m fd_open_data_protocol.registry_cli verify --source-db <db> --by rule:naming-gate
# 自动打印抽样（默认 5 条）作为核验记录；人工核验用 --by <reviewer-id>
```

`register --auto-verify` 会在登记后立即对过门条目执行这一步。

## 覆盖与审计（资产口径）

```bash
python -m fd_open_data_protocol.registry_cli coverage \
    --adapter adapters/<db>.yaml --source-dsn "$FD_SOURCE_DSN" \
    [--module-map modules.json] [--out coverage.json]
```

- 分母 = 源库实际行数（COUNT），**不是** MCP 概念字典数；
- 二期源（ia35、wenshu_db）在覆盖视图中显式出现为「phase 2、未登记」；
- `--module-map`（`{"模块": {"source_dbs": [...]}}`）输出未被任何模块规则
  覆盖的已登记条目（未映射审计）。

## 导出（消费端）

```bash
python -m fd_open_data_protocol.registry_cli export --verified-only --out indicators.json
```

带 `as_of` 的快照，供 fd-open-data-mcp 目录扩容与官网 db_stats 生成化消费；
unverified 条目默认不出现在导出里。

## 安装

```bash
pip install 'fd-open-data-protocol[registry]'   # psycopg3 用于 Postgres 读写
```

测试（全绿为协议收口标准）：`pytest tests/`
