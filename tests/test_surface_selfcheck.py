"""surface_selfcheck 四臂判据的单测（纯 evaluate，不起服务）。"""
from __future__ import annotations

from fd_open_data_protocol.surface_selfcheck import evaluate

RO = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
RW = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}


def _m(groups, annotations=None, rules=None):
    m = {"tool_groups": groups}
    if annotations is not None:
        m["tool_annotations"] = annotations
    if rules is not None:
        m["rules"] = rules
    return m


def test_clean_manifest_passes():
    m = _m([{"group": "read", "level": "commercial", "tools": ["a"]}], {"a": RO})
    r = evaluate(repo="x", manifest=m, runtime={"a"}, runtime_error=None)
    assert r.code == 0, r.problems


def test_jia_multi_declared_and_multi_registered():
    m = _m([{"group": "read", "level": "commercial", "tools": ["a", "b"]}], {"a": RO, "b": RO})
    r = evaluate(repo="x", manifest=m, runtime={"a", "c"}, runtime_error=None)
    assert r.code == 1
    assert any("多声明" in p and "b" in p for p in r.problems)
    assert any("多注册" in p and "c" in p for p in r.problems)


def test_jia_undecidable_is_not_a_defect():
    m = _m([{"group": "read", "level": "commercial", "tools": ["a"]}], {"a": RO})
    r = evaluate(repo="x", manifest=m, runtime=None, runtime_error="ModuleNotFoundError: fastmcp")
    assert r.code == 2, "判不出必须与缺陷分档"
    assert not r.problems
    assert any("fastmcp" in u for u in r.undecidable)


def test_yi_commercial_nonreadonly_without_ceiling_fails():
    m = _m([{"group": "w", "level": "commercial", "tools": ["w"]}], {"w": RW})
    r = evaluate(repo="x", manifest=m, runtime={"w"}, runtime_error=None)
    assert r.code == 1
    assert any("非只读" in p for p in r.problems)


def test_yi_exemption_allows_write_tool():
    m = _m([{"group": "w", "level": "commercial", "tools": ["w"]}], {"w": RW},
           rules={"commercial_exemptions": [{"tool": "w", "reason": "缓存写，不改数据"}]})
    r = evaluate(repo="x", manifest=m, runtime={"w"}, runtime_error=None)
    assert r.code == 0, r.problems


def test_yi_ceiling_lets_legacy_through_but_caps_growth():
    m = _m([{"group": "w", "level": "commercial", "tools": ["w", "v"]}], {"w": RW, "v": RW})
    ok = evaluate(repo="x", manifest=m, runtime={"w", "v"}, runtime_error=None,
                  ceilings={"commercial_nonreadonly": 2})
    assert ok.code == 0, ok.problems
    assert any("2/2" in i for i in ok.info)
    # 上限 1 而实际 2 ⇒ 红（该臂只许变短）
    bad = evaluate(repo="x", manifest=m, runtime={"w", "v"}, runtime_error=None,
                   ceilings={"commercial_nonreadonly": 1})
    assert bad.code == 1


def test_bing_undeclared_annotations_ceiling():
    m = _m([{"group": "read", "level": "commercial", "tools": ["a", "b"]}], None)
    # 无 tool_annotations 字段 ⇒ 两个都未声明
    r = evaluate(repo="x", manifest=m, runtime={"a", "b"}, runtime_error=None)
    assert r.code == 1 and r.counts["undeclared_annotations"] == 2
    ok = evaluate(repo="x", manifest=m, runtime={"a", "b"}, runtime_error=None,
                  ceilings={"undeclared_annotations": 2})
    assert ok.code == 0, ok.problems


def test_partial_hint_set_fails():
    m = _m([{"group": "read", "level": "commercial", "tools": ["a"]}],
           {"a": {"readOnlyHint": True, "destructiveHint": False}})
    r = evaluate(repo="x", manifest=m, runtime={"a"}, runtime_error=None)
    assert r.code == 1
    assert any("缺 hint" in p for p in r.problems)


def test_ding_illegal_level_and_group_conflict():
    m = _m([
        {"group": "a", "level": "bogus", "tools": ["x"]},
        {"group": "b", "level": "commercial", "tools": ["y"]},
        {"group": "c", "level": "internal", "tools": ["y"]},
    ], {"x": RO, "y": RO})
    r = evaluate(repo="x", manifest=m, runtime={"x", "y"}, runtime_error=None)
    assert any("level 非法" in p for p in r.problems)
    assert any("级别冲突" in p for p in r.problems)


def test_rules_commercial_tools_must_match_groups():
    m = _m([{"group": "read", "level": "commercial", "tools": ["a"]}], {"a": RO},
           rules={"commercial_tools": ["a", "zzz"]})
    r = evaluate(repo="x", manifest=m, runtime={"a"}, runtime_error=None)
    assert any("rules.commercial_tools" in p for p in r.problems)


def test_legacy_tools_shape_is_read():
    m = {"tools": [{"name": "a"}, {"name": "b"}], "tool_annotations": {"a": RO, "b": RO}}
    r = evaluate(repo="x", manifest=m, runtime={"a", "b"}, runtime_error=None)
    # 旧形状无 tool_groups ⇒ 无 commercial 集；甲臂仍应通过
    assert r.code == 0, r.problems


def test_exemption_without_reason_fails():
    """豁免必须带理由——只记工具名的豁免等于无理由放行。"""
    m = _m([{"group": "w", "level": "commercial", "tools": ["w"]}], {"w": RW},
           rules={"commercial_exemptions": [{"tool": "w"}]})
    r = evaluate(repo="x", manifest=m, runtime={"w"}, runtime_error=None)
    assert r.code == 1
    assert any("缺理由" in p for p in r.problems)


def test_internal_write_tool_not_in_commercial_arm():
    m = _m([{"group": "adm", "level": "internal", "tools": ["del"]}], {"del": RW})
    r = evaluate(repo="x", manifest=m, runtime={"del"}, runtime_error=None)
    assert r.code == 0, r.problems


def test_ceiling_breach_fails():
    m = _m([{"group": "w", "level": "commercial", "tools": ["a", "b"]}], {"a": RW, "b": RW})
    r = evaluate(repo="x", manifest=m, runtime={"a", "b"}, runtime_error=None,
                 ceilings={"commercial_nonreadonly": 1})
    assert r.code == 1 and any("基线上限" in p for p in r.problems)
