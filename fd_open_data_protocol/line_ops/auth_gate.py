"""HTTP 层鉴权门（ASGI 中间件）——「无 Bearer 拒 / 有 Bearer 放行」。

门不校验凭据真伪：有效性由上游权威判定，坏凭据的 401 在工具层原样透传。
凭据永不落日志，缓存键是 sha256(token)。

本实现对 5 个 ops-mcp 仓通用；线名只出现在错误文本里，由调用方传入。
"""
from __future__ import annotations

import hashlib
import time

#: 缓存条目上限。门的语义是「无 Bearer 拒 / 有 Bearer 放行」，**任意**非空 bearer
#: 都会写一条记录（有效性由上游权威判定），所以键的数量完全由入站流量决定——
#: 一个带随机 token 重试的坏客户端、或一批各自轮换 token 的 agent 就能把它灌满。
#: 键是 sha256（64 字符）加 tuple，每条约 150-200 字节；无上界时长跑进程的 RSS
#: 单调上升，最终 OOM 重启（并在重启后再走一遍启动退避）。
#: 2026-11-09 实测：灌 5000 个不同 bearer 后缓存留 5000 条。
DEFAULT_MAX_ENTRIES = 1024


class AuthGate:
    def __init__(self, ttl_seconds: float = 60.0, max_entries: int = DEFAULT_MAX_ENTRIES):
        self._ttl = ttl_seconds
        self._max = max_entries
        self._cache: dict[str, tuple[float, bool]] = {}

    def _key(self, bearer: str) -> str:
        return hashlib.sha256(bearer.encode()).hexdigest()

    def _evict(self, now: float) -> None:
        """先清过期，再按最旧写入淘汰到上界以内。

        过期清理不是可有可无的：只做容量淘汰的话，TTL 短的条目会把还不该走的
        条目挤出去，白丢一次上游往返。
        """
        if len(self._cache) < self._max:
            for k in [k for k, (ts, _) in self._cache.items() if now - ts >= self._ttl]:
                self._cache.pop(k, None)
            return
        for k in [k for k, (ts, _) in self._cache.items() if now - ts >= self._ttl]:
            self._cache.pop(k, None)
        overflow = len(self._cache) - self._max + 1
        if overflow > 0:
            for k, _ in sorted(self._cache.items(), key=lambda kv: kv[1][0])[:overflow]:
                self._cache.pop(k, None)

    async def check(self, bearer: str | None) -> bool:
        if not bearer:
            return False
        key = self._key(bearer)
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit and now - hit[0] < self._ttl:
            return hit[1]
        self._evict(now)
        self._cache[key] = (now, True)
        return True

    @property
    def cache_size(self) -> int:
        """当前缓存条目数（测试与可观测用）。"""
        return len(self._cache)


class AuthGateMiddleware:
    """薄 ASGI 包装：仅拦 POST /mcp*，其余原样放行（/health 无门）。"""

    def __init__(self, app, gate: AuthGate):
        self.app = app
        self.gate = gate

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        path = (scope.get("path") or "").lstrip("/")
        if path != "mcp" and not path.endswith("/mcp"):
            await self.app(scope, receive, send)
            return
        bearer = bearer_from_scope(scope)
        if await self.gate.check(bearer):
            await self.app(scope, receive, send)
            return
        # 消掉上行 body 再应答，防连接悬挂：读到完整 request 或对端断开即止
        while True:
            msg = await receive()
            if msg.get("type") == "http.disconnect":
                return
            if msg.get("type") == "http.request" and not msg.get("more_body", False):
                break
        await send(
            {
                "type": "http.response.start",
                "status": 401,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": b'{"error": "Authentication required"}',
            }
        )


#: Headers a bearer may arrive in. `authorization` is the standard one; the MCP
#: gateway in front of us forwards the caller's token upstream as
#: `x-authorization` (mcpgw `_get_registry_headers`) and advertises support for
#: both. Reading only the standard header rejected EVERY proxied call with
#: `401 {"error": "Authentication required"}` while a direct request passed —
#: live 2026-11-09: the wire/lex servers were dark behind the gateway and 17
#: packs declaring their tools could not run.
_BEARER_HEADERS = (b"authorization", b"x-authorization")


def bearer_from_scope(scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name not in _BEARER_HEADERS:
            continue
        text = value.decode("latin-1")
        if text.lower().startswith("bearer "):
            token = text[7:].strip()
            if token:
                return token
    return None
