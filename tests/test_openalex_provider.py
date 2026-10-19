"""OpenAlex provider：离线测试（不访问网络）。

覆盖契约要点：礼貌调用、四项命令、失败显式（配额/限流/不可达）、
收录偏差如实标注、CC0 归属。
"""
from __future__ import annotations

import urllib.error

import pytest

from fd_open_data_protocol import openalex_provider as oa


class FakeResp:
    def __init__(self, headers=None):
        self.headers = headers or {}

    def read(self):
        return b"boom"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def close(self):
        return None

    def items(self):
        return list(self.headers.items())


def test_polite_user_agent_carries_mailto():
    assert "mailto:" in oa.UA
    assert "@" in oa.UA.split("mailto:")[-1].strip(")")


def test_quota_headers_recorded(monkeypatch):
    payload = {
        "results": [
            {
                "id": "https://openalex.org/W1",
                "title": "T",
                "publication_year": 2020,
                "cited_by_count": 5,
                "doi": "10.1/x",
            }
        ]
    }

    def fake_urlopen(req, timeout=None):
        assert req.headers.get("User-agent") == oa.UA or req.get_header("User-agent") == oa.UA
        return _json_resp(payload, {"x-ratelimit-limit": "1000"})

    monkeypatch.setattr(oa.urllib.request, "urlopen", fake_urlopen)
    out = oa.OpenAlexProvider().run("get_work", {"doi": "10.1/x"})
    assert out["quota"]["x-ratelimit-limit"] == "1000"
    assert out["source"] == "openalex" and out["license"] == "CC0"


def _json_resp(payload, headers=None):
    class R:
        def __init__(self):
            self.headers = _H(headers or {})

        def read(self):
            return __import__("json").dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    class _H(dict):
        def items(self):
            return list(dict.items(self))

    return R()


def test_search_works_returns_total_and_rows(monkeypatch):
    payload = {
        "meta": {"count": 42},
        "results": [
            {"id": "https://openalex.org/Wa", "title": "A", "publication_year": 2017,
             "cited_by_count": 7},
            {"id": "https://openalex.org/Wb", "title": "B", "publication_year": 2019,
             "cited_by_count": 9},
        ],
    }
    monkeypatch.setattr(oa.urllib.request, "urlopen",
                        lambda req, timeout=None: _json_resp(payload))
    out = oa.OpenAlexProvider().run("search_works", {"query": "q", "limit": 2})
    assert out["total"] == 42 and len(out["results"]) == 2
    assert out["results"][0]["work_id"] == "Wa"


def test_references_and_citations(monkeypatch):
    p = oa.OpenAlexProvider()
    monkeypatch.setattr(oa.urllib.request, "urlopen", lambda req, timeout=None: _json_resp(
        {"id": "https://openalex.org/W1", "referenced_works_count": 2,
         "referenced_works": ["https://openalex.org/Wx", "https://openalex.org/Wy"]}))
    r = p.run("get_references", {"work_id": "W1"})
    assert r["reference_count"] == 2 and r["reference_ids"] == ["Wx", "Wy"]

    monkeypatch.setattr(oa.urllib.request, "urlopen", lambda req, timeout=None: _json_resp(
        {"meta": {"count": 100},
         "results": [{"id": "https://openalex.org/Wc", "title": "C", "publication_year": 2021}]}))
    c = p.run("get_citations", {"work_id": "W1", "limit": 1})
    assert c["total_count"] == 100 and c["results"][0]["citing_work_id"] == "Wc"


def test_quota_error_is_explicit(monkeypatch):
    def raise_429(req, timeout=None):
        raise urllib.error.HTTPError("u", 429, "Too Many Requests", {}, FakeResp())

    monkeypatch.setattr(oa.urllib.request, "urlopen", raise_429)
    with pytest.raises(oa.OpenAlexQuotaExceeded):
        oa.OpenAlexProvider().run("get_work", {"doi": "10.1/x"})


def test_upstream_5xx_is_explicit(monkeypatch):
    def raise_503(req, timeout=None):
        raise urllib.error.HTTPError("u", 503, "Unavailable", {}, FakeResp())

    monkeypatch.setattr(oa.urllib.request, "urlopen", raise_503)
    with pytest.raises(oa.OpenAlexUnavailable):
        oa.OpenAlexProvider().run("get_work", {"doi": "10.1/x"})


def test_unreachable_is_explicit(monkeypatch):
    def raise_urlerr(req, timeout=None):
        raise urllib.error.URLError("dns fail")

    monkeypatch.setattr(oa.urllib.request, "urlopen", raise_urlerr)
    with pytest.raises(oa.OpenAlexUnavailable):
        oa.OpenAlexProvider().run("get_work", {"doi": "10.1/x"})


def test_not_found_states_not_indexed_not_nonexistent(monkeypatch):
    """未收录必须如实说明——不断言「不存在」。"""
    monkeypatch.setattr(oa.urllib.request, "urlopen",
                        lambda req, timeout=None: _json_resp({"results": []}))
    with pytest.raises(ValueError, match="未收录"):
        oa.OpenAlexProvider().run("get_work", {"doi": "10.1/nope"})


def test_missing_identifier_rejected():
    p = oa.OpenAlexProvider()
    with pytest.raises(ValueError):
        p.run("get_references", {})
    with pytest.raises(ValueError):
        p.run("get_work", {})


def test_manifest_validates_and_declares_relationships():
    from fd_open_data_protocol.loader import load_catalog

    m = load_catalog("adapters/academic_openalex.yaml")
    cmds = {f.command for f in m.functions}
    assert {"get_work", "search_works", "get_references", "get_citations"} <= cmds
    rels = {(r.relation_type, r.source_entity_type, r.target_entity_type)
            for r in (m.relationships or [])}
    assert ("cites", "paper", "paper") in rels
    assert ("cited_by", "paper", "paper") in rels
    ents = {e.entity_type for e in (m.entities or [])}
    assert {"paper", "author", "venue", "topic", "institution"} <= ents
