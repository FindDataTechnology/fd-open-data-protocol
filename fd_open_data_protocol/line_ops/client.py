"""Bearer 原样转发的上游客户端（共享实现）。

各线保留自己的错误类名（`LexError` / `WireError` / `RegistryError`）——那是已发布的
内部契约：工具层与测试按名字捕获它，改名会牵动 5 仓的测试与工具层。本模块接受一个
`error_cls` 参数，把「建错」交给调用方，公共部分（httpx、超时、状态码归类、不可达）
收在这里。

凭据只经手不落盘；连接失败 / 5xx 归为 unreachable——不冒充业务错误。
"""
from __future__ import annotations

from typing import Any, Callable


class LineError(Exception):
    """默认错误类：kind + status + 上游 detail 原文。

    各线可传入自己的类（签名须同为 `(kind, status, detail)`）。
    """

    def __init__(self, kind: str, status: int | None, detail: str):
        super().__init__(f"[{kind}] {detail}" + (f" (HTTP {status})" if status else ""))
        self.kind = kind
        self.status = status
        self.detail = detail


class LineClient:
    """Bearer 原样转发 + 诚实错误映射。

    :param base_url: 上游根地址
    :param timeout_seconds: 请求超时
    :param error_cls: 抛出的错误类，签名 `(kind, status, detail)`
    :param service_label: 错误文本里的服务名（如「柏讯」）；不可达时用
    :param transport: 测试注入（httpx transport）
    :param missing_hint: 无凭据时的提示语；None 则用通用文案
    """

    def __init__(
        self,
        base_url: str,
        timeout_seconds: float = 20.0,
        transport=None,
        *,
        error_cls: Callable[[str, int | None, str], Exception] = LineError,
        service_label: str = "上游",
        missing_hint: str | None = None,
    ):
        # httpx 只在真正用客户端时才需要（protocol 的主依赖不含它）；
        # 延迟到这里 import，使「只 import line_ops.auth_gate」的消费方不必装 httpx。
        import httpx
        self._httpx = httpx
        self._client = httpx.AsyncClient(
            base_url=base_url, timeout=timeout_seconds, transport=transport
        )
        self._error = error_cls
        self._label = service_label
        self._missing_hint = missing_hint or f"缺少凭据：{service_label}需要 Bearer"

    async def aclose(self):
        await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        bearer: str | None,
        params: dict | None = None,
        json_body: Any | None = None,
    ) -> Any:
        if not bearer:
            raise self._error("missing_credential", 401, self._missing_hint)
        try:
            res = await self._client.request(
                method,
                path,
                headers={"Authorization": f"Bearer {bearer}"},
                params=params,
                json=json_body,
            )
        except self._httpx.HTTPError as e:
            raise self._error(
                "unreachable", None, f"{self._label}服务不可达：{type(e).__name__}: {e}"
            ) from e
        if res.status_code == 401:
            raise self._error("unauthorized", 401, _detail(res))
        if res.status_code == 402:
            raise self._error("billing", 402, _detail(res))
        if res.status_code == 403:
            raise self._error("forbidden", 403, _detail(res))
        if res.status_code == 404:
            raise self._error("not_found", 404, _detail(res))
        if res.status_code == 409:
            raise self._error("conflict", 409, _detail(res))
        if res.status_code == 422:
            raise self._error("invalid", 422, _detail(res))
        if res.status_code == 429:
            raise self._error("rate_limited", 429, _detail(res))
        if res.status_code >= 500:
            raise self._error("unreachable", res.status_code, f"{self._label}服务错误：{_detail(res)}")
        if res.status_code >= 400:
            raise self._error("invalid", res.status_code, _detail(res))
        if not res.content:
            return None
        try:
            return res.json()
        except ValueError:
            return {"_raw": res.text}


def _detail(res) -> str:
    try:
        body = res.json()
        if isinstance(body, dict) and "detail" in body:
            return str(body["detail"])[:800]
        if isinstance(body, dict) and "error" in body:
            return str(body["error"])[:800]
        return str(body)[:800]
    except Exception:  # noqa: BLE001
        return (res.text or "")[:800] or f"HTTP {res.status_code}（无 body）"
