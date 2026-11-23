"""启动自报共享实现（openspec: mcp-surface-self-report / stabilize-mcp-lifecycle D1）。

从 wire-ops / wanxing-ops / wire-build / paper-trading 四份逐仓副本合并而来——
移植它们原先各自钉住的回归点：上报体构造、两代 fastmcp 枚举 API、有界退避、
无配置静默跳过、fire-and-forget 不阻塞启动、/health 三态属性。
"""

from __future__ import annotations

import asyncio
from typing import ClassVar

import pytest

from fd_open_data_protocol import surface_report as sr


class FakeMCP:
    """fastmcp ≥4.5 形态：get_tools() -> {name: tool}。"""

    def __init__(self, tools):
        self._tools = tools
        self._surface_report = "not_configured"

    async def get_tools(self):
        return {name: object() for name in self._tools}


class FakeMCP4:
    """fastmcp 4.x 早期形态：无 get_tools，只有 list_tools()（Tool 对象序列）。

    2026-10-24 生产实证：只认 get_tools 会在 payload 构造期 AttributeError，
    一次 HTTP 都发不出，启动自报静默失败。
    """

    class _Tool:
        def __init__(self, name):
            self.name = name

    def __init__(self, tools):
        self._tools = tools
        self._surface_report = "not_configured"

    async def list_tools(self):
        return [self._Tool(n) for n in self._tools]


class FakeResp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body or {}
        self.text = str(self._body)

    def json(self):
        return self._body


class FakeClient:
    """httpx 模块替身：暴露 AsyncClient，记录 post 调用。"""

    posts: ClassVar[list] = []
    responses: ClassVar[list] = []

    class _Async:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None):
            FakeClient.posts.append({"url": url, "json": json, "headers": headers})
            rs = FakeClient.responses
            return rs.pop(0) if rs else FakeResp(200, {"num_tools": 1, "updated": True})

    AsyncClient = _Async


_ENV_KEYS = (
    "REGISTRY_INTERNAL_URL", "WIRE_SURFACE_TOKEN", "WIRE_SURFACE_ENTRY_PATH",
    "OPS_SURFACE_TOKEN", "OPS_SURFACE_ENTRY_PATH", "REGISTRY_SURFACE_BACKOFF",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    FakeClient.posts = []
    FakeClient.responses = []


def _configure(monkeypatch, *, prefix="WIRE", path="/wire-build-mcp"):
    monkeypatch.setenv("REGISTRY_INTERNAL_URL", "https://registry.example")
    monkeypatch.setenv(f"{prefix}_SURFACE_TOKEN", "srf_tok")
    monkeypatch.setenv(f"{prefix}_SURFACE_ENTRY_PATH", path)
    monkeypatch.setenv("REGISTRY_SURFACE_BACKOFF", "0,0,0,0")


async def test_not_configured_skips_silently():
    """无配置：返回 False、零网络调用——本地/未上牌形态与现状一致。"""
    assert await sr.report_surface(FakeMCP(["t"]), httpx=FakeClient) is False
    assert FakeClient.posts == []
    assert sr.report_state(False, configured=False) == "not_configured"


async def test_report_payload_and_auth(monkeypatch):
    """上报体=运行时枚举的工具名（排序）+ Bearer 进 Authorization。"""
    _configure(monkeypatch)
    FakeClient.responses = [FakeResp(200, {"num_tools": 2, "updated": True})]

    ok = await sr.report_surface(
        FakeMCP(["wire_artifact_doc_create", "wire_dataset_schema"]), httpx=FakeClient)

    assert ok is True
    post = FakeClient.posts[0]
    assert post["url"] == "https://registry.example/api/surface-report/servers/wire-build-mcp/tool-list"
    assert [t["name"] for t in post["json"]["tools"]] == ["wire_artifact_doc_create", "wire_dataset_schema"]
    assert post["headers"]["Authorization"] == "Bearer srf_tok"


async def test_prefix_derives_its_own_env(monkeypatch):
    """prefix 不同 → 读不同 env、打到不同 path（多服务共用一个实现的前提）。"""
    _configure(monkeypatch, prefix="OPS", path="/fd-paper-trading")
    FakeClient.responses = [FakeResp(200, {})]

    ok = await sr.report_surface(FakeMCP(["t"]), prefix="OPS", httpx=FakeClient)

    assert ok is True
    assert FakeClient.posts[0]["url"].endswith("/api/surface-report/servers/fd-paper-trading/tool-list")
    assert FakeClient.posts[0]["headers"]["Authorization"] == "Bearer srf_tok"


async def test_fastmcp4_list_tools_shape(monkeypatch):
    """fastmcp 4.x（list_tools、无 get_tools）也要枚举成功。"""
    _configure(monkeypatch)
    FakeClient.responses = [FakeResp(200, {})]

    ok = await sr.report_surface(FakeMCP4(["b_tool", "a_tool"]), httpx=FakeClient)

    assert ok is True
    assert [t["name"] for t in FakeClient.posts[0]["json"]["tools"]] == ["a_tool", "b_tool"]


async def test_bounded_retry_then_give_up(monkeypatch):
    """500 一路到底：首发 + 2 轮退避共 3 次，然后放弃、启动不受阻。"""
    _configure(monkeypatch)
    monkeypatch.setenv("REGISTRY_SURFACE_BACKOFF", "0,0")
    FakeClient.responses = [FakeResp(500) for _ in range(10)]

    assert await sr.report_surface(FakeMCP(["t"]), httpx=FakeClient) is False
    assert len(FakeClient.posts) == 3


async def test_retry_succeeds_after_transient(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setenv("REGISTRY_SURFACE_BACKOFF", "0,0")
    FakeClient.responses = [FakeResp(503), FakeResp(200)]

    assert await sr.report_surface(FakeMCP(["t"]), httpx=FakeClient) is True
    assert len(FakeClient.posts) == 2


def test_health_state_transitions():
    assert sr.report_state(True, configured=True) == "ok"
    assert sr.report_state(False, configured=True) == "failed"
    assert sr.report_state(False, configured=False) == "not_configured"


async def test_ensure_started_unconfigured_seals():
    """未配置：一次性封口，不停重试。"""
    mcp = FakeMCP(["t"])
    sr.ensure_started(mcp)
    assert mcp._surface_task is False
    sr.ensure_started(mcp)  # 再调一次仍是 False，不换对象
    assert mcp._surface_task is False


async def test_start_background_marks_state(monkeypatch):
    """/health 读的属性名必须与实现写入的一致——这是换库最容易静默踩的接缝。"""
    _configure(monkeypatch)

    async def fake_report(mcp, *, prefix="WIRE", httpx=None):
        return True

    monkeypatch.setattr(sr, "report_surface", fake_report)

    mcp = FakeMCP(["t"])
    task = sr.start_background(mcp)
    assert task is not None
    await asyncio.wait_for(task, 5)
    assert mcp._surface_report == "ok"


async def test_start_background_marks_failed_state(monkeypatch):
    _configure(monkeypatch)

    async def failing_report(mcp, *, prefix="WIRE", httpx=None):
        raise RuntimeError("boom inside runner")

    monkeypatch.setattr(sr, "report_surface", failing_report)

    mcp = FakeMCP(["t"])
    task = sr.start_background(mcp)
    await asyncio.wait_for(task, 5)
    assert mcp._surface_report == "failed"
