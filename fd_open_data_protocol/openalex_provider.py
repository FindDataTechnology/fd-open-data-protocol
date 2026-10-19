"""OpenAlex 学术图谱数据源 provider（CC0，免费）。

契约要点（对应 academic-graph-connector spec）：
  - 礼貌调用：请求带含 mail 的 User-Agent（免费档 1000 credits/次级）
  - 失败显式：配额/限流/不可达分别报错，**禁止返回空结果冒充无数据**
  - 收录偏差：未收录如实标注，不断言「不存在引用」
  - 引用图是增益，不替代既有 papers 检索
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .provider import BaseDataProvider

API = "https://api.openalex.org"
DEFAULT_MAILTO = os.environ.get("OPENALEX_MAILTO", "ops@finddata.dev")
TIMEOUT = float(os.environ.get("OPENALEX_TIMEOUT", "25"))

# 礼貌调用：OpenAlex 要求可识别的 User-Agent（含 mail），否则可能被限流
UA = f"finddata-academic-connector/1.0 (mailto:{DEFAULT_MAILTO})"


class OpenAlexUnavailable(RuntimeError):
    """上游不可用/不可达——显式失败，不静默返回空。"""


class OpenAlexQuotaExceeded(RuntimeError):
    """配额/限流——显式失败，不冒充「无数据」。"""


class OpenAlexProvider(BaseDataProvider):
    name = "academic-openalex"

    def registry(self) -> dict:
        return {"manifest": "academic_openalex.yaml"}

    def run(self, command: str, params: dict) -> Any:
        handlers = {
            "get_work": self.get_work,
            "search_works": self.search_works,
            "get_references": self.get_references,
            "get_citations": self.get_citations,
        }
        if command not in handlers:
            raise ValueError(f"unknown command {command!r}")
        return handlers[command](params or {})

    # ------------------------------------------------------------------ HTTP

    def _get(self, path: str, params: dict[str, Any] | None = None) -> tuple[dict, dict]:
        """GET 并返回 (payload, quota_headers)。失败显式抛错。"""
        url = f"{API}/{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(
            url, headers={"User-Agent": UA, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = json.loads(resp.read().decode("utf-8", "replace"))
                headers = dict(resp.headers.items())
        except urllib.error.HTTPError as exc:
            # 429 或 5xx 都要区分清楚：前者是配额，后者是上游故障
            if exc.code == 429:
                raise OpenAlexQuotaExceeded(
                    f"OpenAlex rate limit / quota exceeded (HTTP 429): {exc.read()[:200]!r}"
                ) from exc
            if 500 <= exc.code < 600:
                raise OpenAlexUnavailable(
                    f"OpenAlex upstream unavailable (HTTP {exc.code})"
                ) from exc
            raise OpenAlexUnavailable(
                f"OpenAlex request failed (HTTP {exc.code}): {exc.read()[:200]!r}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise OpenAlexUnavailable(f"OpenAlex unreachable: {exc}") from exc
        quota = {
            k.lower(): v
            for k, v in headers.items()
            if k.lower().startswith("x-ratelimit") or k.lower() == "retry-after"
        }
        return raw, quota

    def _resolve_work_id(self, params: dict) -> str:
        """按 work_id 或 doi 定位作品。两者皆缺则报错（不猜）。"""
        work_id = (params.get("work_id") or "").strip()
        doi = (params.get("doi") or "").strip()
        if not work_id and not doi:
            raise ValueError("get_references/get_citations requires `work_id` or `doi`")
        if work_id:
            # 允许传完整 URL，统一取末段
            return work_id.rstrip("/").split("/")[-1]
        payload, _ = self._get(
            "works",
            {"filter": f"doi:{doi}", "select": "id", "per-page": "1"},
        )
        results = payload.get("results") or []
        if not results:
            raise ValueError(
                f"work not found in OpenAlex for doi={doi!r} "
                f"（未收录，不等于该作品不存在）"
            )
        return str(results[0]["id"]).rstrip("/").split("/")[-1]

    # ------------------------------------------------------------- commands

    def get_work(self, params: dict) -> dict:
        doi = (params.get("doi") or "").strip()
        if not doi:
            raise ValueError("get_work requires `doi`")
        payload, quota = self._get(
            "works", {"filter": f"doi:{doi}", "per-page": "1"}
        )
        results = payload.get("results") or []
        if not results:
            # 未收录 ≠ 不存在：如实说明
            raise ValueError(
                f"work not found in OpenAlex for doi={doi!r} （未收录，不等于该作品不存在）"
            )
        w = results[0]
        return {
            "work_id": str(w.get("id", "")).rstrip("/").split("/")[-1],
            "title": w.get("title"),
            "year": w.get("publication_year"),
            "venue": (w.get("primary_location") or {}).get("source", {}).get("display_name")
            if isinstance(w.get("primary_location"), dict)
            else None,
            "cited_by_count": w.get("cited_by_count"),
            "doi": w.get("doi"),
            "source": "openalex",
            "license": "CC0",
            "quota": quota,
        }

    def search_works(self, params: dict) -> dict:
        query = (params.get("query") or "").strip()
        if not query:
            raise ValueError("search_works requires `query`")
        limit = int(params.get("limit") or 10)
        payload, quota = self._get(
            "works",
            {
                "search": query,
                "per-page": str(min(limit, 200)),
                "select": "id,title,publication_year,cited_by_count",
            },
        )
        rows = []
        for w in payload.get("results") or []:
            rows.append(
                {
                    "work_id": str(w.get("id", "")).rstrip("/").split("/")[-1],
                    "title": w.get("title"),
                    "year": w.get("publication_year"),
                    "cited_by_count": w.get("cited_by_count"),
                }
            )
        return {
            "total": (payload.get("meta") or {}).get("count"),
            "results": rows,
            "source": "openalex",
            "license": "CC0",
            "quota": quota,
        }

    def get_references(self, params: dict) -> dict:
        work_id = self._resolve_work_id(params)
        payload, quota = self._get(
            f"works/{work_id}", {"select": "id,referenced_works_count,referenced_works"}
        )
        refs = payload.get("referenced_works") or []
        return {
            "work_id": work_id,
            "reference_count": payload.get("referenced_works_count"),
            "reference_ids": [str(r).rstrip("/").split("/")[-1] for r in refs],
            "source": "openalex",
            "license": "CC0",
            "quota": quota,
        }

    def get_citations(self, params: dict) -> dict:
        work_id = self._resolve_work_id(params)
        limit = int(params.get("limit") or 10)
        payload, quota = self._get(
            "works",
            {
                "filter": f"cites:{work_id}",
                "per-page": str(min(limit, 200)),
                "select": "id,title,publication_year",
            },
        )
        rows = []
        for w in payload.get("results") or []:
            rows.append(
                {
                    "citing_work_id": str(w.get("id", "")).rstrip("/").split("/")[-1],
                    "title": w.get("title"),
                    "year": w.get("publication_year"),
                }
            )
        return {
            "work_id": work_id,
            "total_count": (payload.get("meta") or {}).get("count"),
            "results": rows,
            "source": "openalex",
            "license": "CC0",
            "quota": quota,
        }
