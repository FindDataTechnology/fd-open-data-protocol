"""把「运行时 + 该线工具集」装配成完整 ASGI 应用。

一个线服务 = 「FastMCP 实例（注册了这条线的工具）」+「鉴权门」+「/health」+
「线自描述」。前三件事每个仓都写一遍且近乎相同；本模块把它们收成一次 `assemble()`。
各仓只提供 `build_mcp`（建 FastMCP 并注册自己的工具）与 settings。
"""
from __future__ import annotations

from typing import Any, Callable

from .auth_gate import AuthGate, AuthGateMiddleware
from .wellknown import WELL_KNOWN_PATH, manifest_response

_HEALTH_OK = b'{"status":"ok"}'
_HEALTH_OK_REPORTED = b'{"status":"ok","last_surface_report":"ok"}'
_HEALTH_FAILED_REPORTED = b'{"status":"ok","last_surface_report":"failed"}'


def assemble(
    build_mcp: Callable[[], Any],
    *,
    auth_cache_ttl_seconds: float = 60.0,
    mcp_path: str = "/mcp",
    enable_surface_report: bool = True,
    gate_cls: Callable[[Any, AuthGate], Any] | None = None,
    manifest_anchor: str | None = None,
):
    """返回完整 ASGI app：/health 与线自描述免门，其余走鉴权门（无 Bearer 拒）。

    :param build_mcp: 无参可调用，返回一个 FastMCP 实例（工具已注册）
    :param auth_cache_ttl_seconds: 鉴权缓存 TTL（来自该线 settings）
    :param mcp_path: MCP 端点路径
    :param enable_surface_report: 是否在首请求触发 `surface_report.ensure_started`。
        该机制要求服务对象带 `_surface_report` 属性；本模块会初始化它。
    :param gate_cls: 鉴权门中间件类，签名 `(app, gate)`。默认用共享实现；
        消费仓传入自己 re-export 的那个名字，使测试 `monkeypatch.setattr(server,
        "AuthGateMiddleware", …)` 能真的替换掉本函数里用的类。
    :param manifest_anchor: 用来定位消费仓 `line-manifest.json` 的文件路径。
        **消费仓必须传自己的**（通常 `__file__`）：不传就按 protocol 包的
        位置推导，仓根会算错（见 `wellknown.manifest_candidates`）。
    """
    mcp = build_mcp()
    if enable_surface_report and not hasattr(mcp, "_surface_report"):
        mcp._surface_report = "not_configured"
    mcp_app = mcp.http_app(path=mcp_path)
    _gate_cls = gate_cls or AuthGateMiddleware
    gate = _gate_cls(mcp_app, AuthGate(auth_cache_ttl_seconds))

    if enable_surface_report:
        from fd_open_data_protocol import surface_report as _sr
    else:
        _sr = None

    async def app(scope, receive, send):
        if scope.get("type") == "http":
            if _sr is not None:
                _sr.ensure_started(mcp)  # 首请求触发：loop 已在跑
            path = (scope.get("path") or "").rstrip("/")
            if path == "/health":
                state = getattr(mcp, "_surface_report", "not_configured")
                body = {
                    "not_configured": _HEALTH_OK,
                    "ok": _HEALTH_OK_REPORTED,
                    "failed": _HEALTH_FAILED_REPORTED,
                }.get(state, _HEALTH_OK)
                await send({"type": "http.response.start", "status": 200,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": body})
                return
            # 线自描述：公开元数据，必须在鉴权门**之前**应答（与 /health 同理），
            # 否则平台/客户在未持有本线凭据时连「这条线认哪些钥匙」都读不到。
            if path == WELL_KNOWN_PATH.rstrip("/"):
                status, body, headers = manifest_response(manifest_anchor)
                await send({"type": "http.response.start", "status": status,
                            "headers": headers + [(b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
        await gate(scope, receive, send)

    return app
