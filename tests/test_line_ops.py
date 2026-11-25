"""line_ops 共享运行时的测试（line-ops-runtime-core 的四条要求）。"""
from __future__ import annotations

import asyncio

from fd_open_data_protocol.line_ops import (
    AuthGate,
    AuthGateMiddleware,
    bearer_from_scope,
    make_settings_class,
)


# ── 有界缓存 ──────────────────────────────────────────────────────────────

def test_cache_is_bounded_under_many_bearers():
    """灌远超上界的 bearer，缓存条目数不超过上界（这是 wire-ops 2026-11-09 的实测缺陷）。"""
    gate = AuthGate(ttl_seconds=60.0, max_entries=100)
    for i in range(5000):
        asyncio.run(gate.check(f"token-{i}"))
    assert gate.cache_size <= 100, gate.cache_size


def test_expired_entries_evicted_before_live_ones():
    gate = AuthGate(ttl_seconds=0.0001, max_entries=10)
    asyncio.run(gate.check("old"))
    import time
    time.sleep(0.01)  # 让它过期
    for i in range(9):
        asyncio.run(gate.check(f"live-{i}"))
    # 过期条目应被清掉，live 的仍在
    assert gate.cache_size <= 9


def test_cache_key_is_irreversible():
    gate = AuthGate()
    key = gate._key("secret-token-value")
    assert "secret-token-value" not in key
    assert len(key) == 64  # sha256 hex


# ── 门的语义 ──────────────────────────────────────────────────────────────

def test_no_bearer_is_rejected():
    gate = AuthGate()
    assert asyncio.run(gate.check(None)) is False
    assert asyncio.run(gate.check("")) is False


def test_any_bearer_passes_gate():
    """门的语义：有 Bearer 放行（真伪由上游权威判）。"""
    gate = AuthGate()
    assert asyncio.run(gate.check("anything")) is True


def test_bearer_from_x_authorization_header():
    """网关把调用方 token 以 x-authorization 转发；只读标准头会让全部代理调用 401。"""
    scope = {"headers": [(b"x-authorization", b"Bearer proxied-token")]}
    assert bearer_from_scope(scope) == "proxied-token"


def test_bearer_from_standard_header():
    scope = {"headers": [(b"authorization", b"Bearer direct-token")]}
    assert bearer_from_scope(scope) == "direct-token"


def test_401_response_does_not_echo_credential():
    """错误响应体内不出现凭据任何部分（line-ops-runtime-core「凭据不落日志」）。"""
    sent = []

    async def app(scope, receive, send):
        raise AssertionError("不该放行")

    async def receive():
        return {"type": "http.request", "more_body": False}

    async def send(msg):
        sent.append(msg)

    mw = AuthGateMiddleware(app, AuthGate())
    scope = {"type": "http", "method": "POST", "path": "/mcp",
             "headers": [(b"authorization", b"Bearer ")]}  # 空 token ⇒ 拒
    asyncio.run(mw(scope, receive, send))
    body = b"".join(m.get("body", b"") for m in sent)
    assert b"Authentication required" in body
    assert b"Bearer" not in body


def test_health_path_bypasses_gate():
    """非 /mcp 路径不走门（/health 无门）。"""
    calls = []

    async def app(scope, receive, send):
        calls.append(scope.get("path"))

    async def receive():
        return {"type": "http.request"}

    async def send(msg):
        pass

    mw = AuthGateMiddleware(app, AuthGate())
    asyncio.run(mw({"type": "http", "method": "POST", "path": "/health", "headers": []},
                   receive, send))
    assert calls == ["/health"]


# ── 配置 ──────────────────────────────────────────────────────────────────

def test_settings_prefix_and_defaults():
    S = make_settings_class("WIRE_OPS", "https://wire.finddatatech.cloud")
    s = S.from_env({})
    assert s.base_url == "https://wire.finddatatech.cloud"
    assert s.timeout_seconds == 20.0
    assert s.auth_cache_ttl_seconds == 60.0


def test_settings_reads_prefixed_env_and_strips_slash():
    S = make_settings_class("LEX_OPS", "https://lex.finddatatech.cloud")
    s = S.from_env({"LEX_OPS_BASE_URL": "http://127.0.0.1:8000/",
                    "LEX_OPS_TIMEOUT_SECONDS": "5",
                    "LEX_OPS_AUTH_CACHE_TTL": "30"})
    assert s.base_url == "http://127.0.0.1:8000"  # 尾斜杠去掉
    assert s.timeout_seconds == 5.0
    assert s.auth_cache_ttl_seconds == 30.0


def test_two_lines_dont_share_env():
    W = make_settings_class("WIRE_OPS", "https://wire.example")
    L = make_settings_class("LEX_OPS", "https://lex.example")
    assert W.from_env({"LEX_OPS_BASE_URL": "https://lex.example"}).base_url == "https://wire.example"
    assert L.from_env({"WIRE_OPS_BASE_URL": "https://wire.example"}).base_url == "https://lex.example"
