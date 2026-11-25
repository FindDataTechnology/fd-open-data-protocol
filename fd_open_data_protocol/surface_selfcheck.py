"""tool-surface manifest 的共享 selfcheck（mcp-surface-contract / mcp-surface-truth）。

## 为什么存在

`scripts/selfcheck_surface.py` 在各仓是 ~55 行的近同副本（17 份），差异只在「怎么把
服务建起来」那一行。同时它们的判据覆盖面**不一致**：只有 `fd-open-data-mcp` 那一份
检查了「commercial 集内是否只含只读工具」，其余 16 份只做 manifest↔运行时双向比对。
多份复制必然漂移——这是本工作区反复踩过的同一形状（`surface_report.py` 从三份逐仓
副本抽成共享实现是同一判断）。

## 四臂判据（与 `mcp-surface-contract`「selfcheck 双向断言」逐条对应）

1. **甲｜双向一致**：manifest 声明的工具集 == 运行时注册的工具集。多声明/多注册都红。
   存量：已全绿（17 仓副本都做这一臂）。
2. **乙｜commercial 只读**：`commercial` 集内每个工具的 `readOnlyHint` 为 true，或在
   `rules.commercial_exemptions` 里登记并附理由。存量：只有 1 仓达标——故本臂按仓
   用基线上限（`#: 上限 N`）承接，只许变短。
3. **丙｜行为属性齐备**：每个工具在 `tool_annotations` 里声明四个 hint。存量：8 仓零
   声明——同乙臂，按仓登记上限。
4. **丁｜级别合法**：每组 `level` ∈ {commercial, internal}；同一工具不得在两组间级别
   冲突。无存量问题，恒判。

## 三档退出码

`0` 通过 / `1` 有缺陷 / `2` 判不出。**判不出明确不是缺陷**：运行时入口导入失败（依赖
未装、venv 版本低于声明）时，回落到 manifest 自述会让「运行时从未被验证」看起来像
通过（`audit-gate-can-check-the-wrong-machine`），所以宁可报判不出。

## 用法

    from fd_open_data_protocol.surface_selfcheck import run_selfcheck
    raise SystemExit(run_selfcheck(
        manifest_path=Path("tool-surface.json"),
        repo_root=Path("."),
        build_server=lambda: make_server(),      # 返回一个 FastMCP 实例
        ceilings={"ying_commercial_nonreadonly": 12, "bing_undeclared": 87},
    ))

各仓可以继续用自己的 `scripts/selfcheck_surface.py` 包一层（保持既有调用方式），内部
改成调本模块。
"""
from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

HINTS = ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint")

#: 两个「存量上限」臂的键名。语义：当前有多少个不合规项，只许变短。
CEIL_COMMERCIAL_NONREADONLY = "commercial_nonreadonly"
CEIL_UNDECLARED = "undeclared_annotations"


@dataclass
class Report:
    repo: str
    problems: list[str] = field(default_factory=list)
    undecidable: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    #: 甲臂因环境限制被跳过时置真：使 code 仍为 0（其余臂通过），
    #: 但输出里保留「这一臂没验」的事实（不把「验不了」写成「通过」）。
    runtime_unverified: bool = False

    @property
    def code(self) -> int:
        if self.problems:
            return 1
        if self.undecidable:
            return 2
        return 0


def _levels(manifest: dict) -> tuple[dict[str, str], list[str]]:
    """丁臂：级别合法 + 无组间冲突。返回 (tool→level, problems)。"""
    levels: dict[str, str] = {}
    problems: list[str] = []
    for g in manifest.get("tool_groups", []) or []:
        lv = g.get("level")
        if lv not in ("commercial", "internal"):
            problems.append(f"tool_groups.{g.get('group')} 的 level 非法：{lv!r}")
            continue
        for t in g.get("tools", []) or []:
            if t in levels and levels[t] != lv:
                problems.append(f"工具 {t} 在多个 group 中级别冲突（{levels[t]} vs {lv}）")
            levels[t] = lv
    return levels, problems


def _declared_fallback(manifest: dict) -> set[str]:
    """旧形状 `tools: [{name}]` 的声明集（只有本模块的甲臂会用到，判不出时不使用）。"""
    out = set()
    for t in manifest.get("tools", []) or []:
        if isinstance(t, dict) and t.get("name"):
            out.add(t["name"])
    return out


def _runtime_names(build_server: Callable[[], Any]) -> tuple[set[str] | None, str | None]:
    try:
        server = build_server()
        tools = asyncio.run(server.list_tools()) if not asyncio.iscoroutine(server) else asyncio.run(server.list_tools())
        return {t.name for t in tools}, None
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"


def evaluate(
    *,
    repo: str,
    manifest: dict,
    runtime: set[str] | None,
    runtime_error: str | None,
    ceilings: dict[str, int] | None = None,
) -> Report:
    """纯函数：给 manifest + 运行时工具集，产出报告。便于单测，无需起服务。"""
    ceilings = ceilings or {}
    r = Report(repo=repo)

    levels, level_problems = _levels(manifest)
    r.problems.extend(level_problems)
    declared = set(levels) or _declared_fallback(manifest)

    # ── 甲：双向一致 ──
    if runtime is None:
        r.undecidable.append(
            f"运行时入口不可用（{runtime_error}）——无法验证 manifest↔运行时一致，判不出而非通过")
    else:
        extra = declared - runtime
        missing = runtime - declared
        if extra:
            r.problems.append(f"manifest 多声明（代码未注册）：{sorted(extra)}")
        if missing:
            r.problems.append(f"代码多注册（manifest 未声明）：{sorted(missing)}")
        r.counts["runtime_tools"] = len(runtime)

    annotations: dict[str, Any] = manifest.get("tool_annotations") or {}
    commercial = {t for t, lv in levels.items() if lv == "commercial"}

    # ── 乙：commercial 只读（或豁免） ──
    rules = manifest.get("rules") or {}
    exemptions = rules.get("commercial_exemptions") or []
    # 豁免必须带理由（mcp-surface-contract：「登记在商用豁免台账中并附一句理由」）。
    # 只记工具名不写理由的豁免等于无理由放行——与「整体豁免」同形，故判缺陷。
    exempt: set[str] = set()
    for e in exemptions:
        t = e.get("tool") if isinstance(e, dict) else None
        reason = (e.get("reason") or "").strip() if isinstance(e, dict) else ""
        if not t:
            r.problems.append(f"commercial_exemptions 有条目缺 tool：{e!r}")
            continue
        if not reason:
            r.problems.append(f"豁免 {t} 缺理由（修法：补一句「为什么它虽写仍可商用」）")
        exempt.add(t)
    nonreadonly: list[str] = []
    for t in sorted(commercial):
        a = annotations.get(t)
        if not isinstance(a, dict):
            continue  # 无属性由丙臂计，不在乙臂重复计
        if a.get("readOnlyHint") is not True and t not in exempt:
            nonreadonly.append(t)
    # rules.commercial_tools 与组级 level 的一致性（有 rules 时才查）
    if rules.get("commercial_tools") is not None:
        if set(rules["commercial_tools"]) != commercial:
            r.problems.append("rules.commercial_tools 与组级 level=commercial 的工具集不一致")
    r.counts[CEIL_COMMERCIAL_NONREADONLY] = len(nonreadonly)
    ceil = ceilings.get(CEIL_COMMERCIAL_NONREADONLY)
    if nonreadonly:
        if ceil is None:
            r.problems.append(
                f"commercial 集含 {len(nonreadonly)} 个非只读且未豁免的工具：{nonreadonly}"
                "（修法：补 rules.commercial_exemptions 并写理由，或移出 commercial；"
                "存量可登记 ceilings.commercial_nonreadonly）")
        elif len(nonreadonly) > ceil:
            r.problems.append(
                f"commercial 非只读工具数 {len(nonreadonly)} > 基线上限 {ceil}（只许变短）：{nonreadonly}")
        else:
            r.info.append(f"commercial 非只读 {len(nonreadonly)}/{ceil}（基线上限，只许变短）")

    # ── 丙：行为属性齐备 ──
    undeclared = sorted(t for t in declared if not isinstance(annotations.get(t), dict))
    r.counts[CEIL_UNDECLARED] = len(undeclared)
    ceil_c = ceilings.get(CEIL_UNDECLARED)
    if undeclared:
        if ceil_c is None:
            r.problems.append(
                f"{len(undeclared)} 个工具未声明行为属性（tool_annotations）：{undeclared[:10]}"
                + ("…" if len(undeclared) > 10 else "")
                + "（存量可登记 ceilings.undeclared_annotations）")
        elif len(undeclared) > ceil_c:
            r.problems.append(
                f"未声明行为属性的工具数 {len(undeclared)} > 基线上限 {ceil_c}（只许变短）")
        else:
            r.info.append(f"未声明行为属性 {len(undeclared)}/{ceil_c}（基线上限，只许变短）")

    # ── 补充：已声明者的 hint 必须齐四个键 ──
    for t, a in sorted(annotations.items()):
        if isinstance(a, dict):
            miss = [h for h in HINTS if h not in a]
            if miss:
                r.problems.append(f"{t}: tool_annotations 缺 hint {miss}")
    return r


def run_selfcheck(
    *,
    manifest_path: Path,
    repo_root: Path,
    build_server: Callable[[], Any] | None,
    ceilings: dict[str, int] | None = None,
    repo: str | None = None,
) -> int:
    """走完整流程：读 manifest → 建服务枚举运行时 → evaluate → 打印 → 返回退出码。"""
    name = repo or repo_root.resolve().name
    if not manifest_path.is_file():
        print(f"SELFCHECK FAIL [{name}]: manifest 缺失：{manifest_path}（契约：缺失即未上牌）")
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    runtime: set[str] | None = None
    runtime_error: str | None = None
    if build_server is not None:
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        runtime, runtime_error = _runtime_names(build_server)

    r = evaluate(repo=name, manifest=manifest, runtime=runtime,
                 runtime_error=runtime_error, ceilings=ceilings)

    tag = {0: "PASS", 1: "FAIL", 2: "UNDECIDABLE"}[r.code]
    print(f"SELFCHECK {tag} [{name}]: {r.counts.get('runtime_tools', '?')} 运行时工具")
    for p in r.problems:
        print(f"  ✗ {p}")
    for p in r.undecidable:
        print(f"  ? {p}")
    for p in r.info:
        print(f"  · {p}")
    return r.code
