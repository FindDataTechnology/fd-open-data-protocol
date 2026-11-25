"""线操作 MCP 服务的共享运行时（`line-ops-runtime-core`）。

## 为什么存在

`lex-ops-mcp` / `wire-ops-mcp` / `facet-ops-mcp` / `wanxing-ops-mcp` / `wire-build-mcp`
五个仓各自维护一份近同的 `auth_gate.py` / `client.py` / `config.py`（规范化线名后逐行
相同，差异只剩注释与格式）。代价不是「多写了几百行」，而是**修复到不了没被撞的那几份**：
2026-11-09 给 wire-ops 的鉴权缓存加上界（灌 5000 个不同 bearer 后缓存留 5000 条），
另外四个仓的 `_cache` 至今无上界。

同类先例是 `surface_report.py`——从三份逐仓副本抽成单一实现，本模块族走同一条路。

## 三个模块，各一件事

- `auth_gate`：HTTP 层「无 Bearer 拒 / 有 Bearer 放行」门，缓存有界、键不可逆。
- `client`：Bearer 原样转发的上游客户端，错误按 kind 归类、凭据不落盘。
- `config`：环境驱动配置，前缀参数化（各线用自己的前缀，如 `WIRE_OPS_`）。

## 消费方式

各仓只保留自己的 `tools_<line>.py` 与 `server.py`（`create_server` 里注册工具），
运行时部分 import 本模块。`line-ops-runtime-core` 的硬约束：升级前后各仓对外
`tools/list` 逐名不变——以「能启动」「测试通过」作为迁移完成判据不成立。
"""
from __future__ import annotations

from .assemble import assemble
from .auth_gate import AuthGate, AuthGateMiddleware, bearer_from_scope
from .client import LineClient, LineError
from .config import LineSettings, make_settings_class
from .wellknown import WELL_KNOWN_PATH, manifest_response

__all__ = [
    "assemble",
    "AuthGate",
    "AuthGateMiddleware",
    "bearer_from_scope",
    "LineClient",
    "LineError",
    "LineSettings",
    "make_settings_class",
    "WELL_KNOWN_PATH",
    "manifest_response",
]
