#!/usr/bin/env python3
"""CI gate: a vocabulary release may only add to the previous released one.

The rule this enforces is the reason the vocabulary can be pinned by consumers:
an entry id is an identity (its URI embeds it), so deleting one or renaming it
silently orphans every instance that used it, and the old meaning is gone. A
release retires an entry with ``superseded_by`` instead.

Usage::

    python scripts/check_vocabulary_additive.py                    # vs latest release tag
    python scripts/check_vocabulary_additive.py --baseline v0.3.2  # vs a named tag
    python scripts/check_vocabulary_additive.py --baseline /tmp/prev-vocabulary
    python scripts/check_vocabulary_additive.py --vocabulary /tmp/candidate

Exit codes: ``0`` additive, ``1`` the release removes/renames something, ``2``
the check could not run at all (bad ref, unreadable directory, no kernel).

Output discipline: on failure one line names what was removed and what to do
instead, shaped ``词表 · 断言 · 事实 · 修法：...`` — never a bare "failed".
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
VOCABULARY_SUBPATH = Path("fd_open_data_protocol") / "vocabulary"


class _CannotRun(RuntimeError):
    """The check never reached a verdict; the message says what to fix."""


def _cannot_run(message: str) -> "None":
    """Abort with exit 2: nothing was verified, so nothing may look verified."""
    raise _CannotRun(message)


def _repository_root() -> Optional[Path]:
    """The checkout this script lives in, or None when not in a git tree."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return Path(out.stdout.strip())


def _latest_release_tag(root: Path) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=root, capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def _materialise_ref(root: Path, ref: str, into: Path) -> Path:
    """Extract ``<ref>:fd_open_data_protocol/vocabulary`` into ``into``.

    Only that subtree is extracted, so comparing against an old tag never drags
    a whole historical checkout into the working tree.
    """
    with tempfile.TemporaryDirectory() as staging:
        archive = Path(staging) / "vocabulary.tar"
        with archive.open("wb") as handle:
            proc = subprocess.run(
                ["git", "archive", "--format=tar", ref, str(VOCABULARY_SUBPATH)],
                cwd=root, stdout=handle, stderr=subprocess.PIPE,
            )
        if proc.returncode != 0:
            detail = proc.stderr.decode("utf-8", "replace").strip()
            _cannot_run(
                f"基线 · ref · 无法从 {ref!r} 取出词表：{detail} · "
                f"修法：确认 ref 存在（git tag --list），或改用 --baseline <目录>"
            )
        with tarfile.open(archive) as tar:
            # Only this repo's own vocabulary subtree is inside, and it comes from
            # our own git history — but pin the extraction policy anyway so the
            # mode does not change when Python's default filter changes.
            tar.extractall(staging, filter="data")
        extracted = Path(staging) / VOCABULARY_SUBPATH
        if not extracted.is_dir():
            _cannot_run(
                f"基线 · ref · {ref!r} 里没有 {VOCABULARY_SUBPATH} · "
                f"修法：换一个包含词表的 ref"
            )
        shutil.copytree(extracted, into)
    return into


def _ensure_kernel(kernel_path: Optional[Path]) -> None:
    """Make the shared kernel importable, or fail with a fixable message.

    The kernel is a *soft* dependency of this library on purpose (services
    install it from outside the workspace). The additive rule is owned by the
    kernel, so this one check cannot run without it — say so instead of quietly
    skipping, which would turn "unchecked" into an apparent pass.
    """
    try:
        import fd_ontology_kernel  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    candidates = [kernel_path] if kernel_path else [REPO_ROOT.parent / "fd-ontology-kernel"]
    for candidate in candidates:
        if candidate and (candidate / "fd_ontology_kernel").is_dir():
            sys.path.insert(0, str(candidate))
            try:
                import fd_ontology_kernel  # noqa: F401
                print(f"note: using kernel from {candidate}", file=sys.stderr)
                return
            except ModuleNotFoundError:
                sys.path.pop(0)
    _cannot_run(
        "词表 · 前置 · 只增不减判据由 fd-ontology-kernel 持有，当前环境装不到它 · "
        "修法：pip install ./fd-ontology-kernel，或用 --kernel-path 指向它的检出目录"
    )


def _load_api():
    from fd_open_data_protocol.vocabulary import (  # noqa: PLC0415 - after sys.path fix
        VocabularyError,
        assert_additive,
        load_vocabulary,
    )
    return VocabularyError, assert_additive, load_vocabulary


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI wrapper: turns an unverifiable run into exit 2 and a named reason."""
    try:
        return _run(argv)
    except _CannotRun as exc:
        print(str(exc), file=sys.stderr)
        return 2


def _run(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="check_vocabulary_additive",
        description="Assert the shipped vocabulary only adds to a previous release.",
    )
    parser.add_argument(
        "--baseline", default=None,
        help="previous release: a git ref or a directory (default: latest release tag)",
    )
    parser.add_argument(
        "--vocabulary", default=None, type=Path,
        help="candidate vocabulary directory (default: the shipped one)",
    )
    parser.add_argument(
        "--kernel-path", default=None, type=Path,
        help="checkout of fd-ontology-kernel to import when it is not installed",
    )
    args = parser.parse_args(argv)

    _ensure_kernel(args.kernel_path)
    VocabularyError, assert_additive, load_vocabulary = _load_api()

    current = args.vocabulary or (REPO_ROOT / VOCABULARY_SUBPATH)
    if not current.is_dir():
        _cannot_run(f"词表 · 目录 · 候选词表目录不存在：{current} · 修法：检查 --vocabulary 路径")

    with tempfile.TemporaryDirectory() as scratch:
        baseline_dir: Optional[Path] = None
        baseline_label = args.baseline
        if args.baseline is None:
            root = _repository_root()
            tag = _latest_release_tag(root) if root is not None else None
            if tag is None:
                _cannot_run(
                    "词表 · 基线 · 没有已发布 tag 可作基线（首次发布没有可比对象）· "
                    "修法：打 tag 或用 --baseline <目录|ref> 指定基线"
                )
            baseline_label = tag
            baseline_dir = _materialise_ref(root, tag, Path(scratch) / "baseline")
        else:
            candidate = Path(args.baseline).expanduser()
            if candidate.is_dir():
                baseline_dir = candidate
            else:
                root = _repository_root()
                if root is None:
                    _cannot_run(
                        f"词表 · 基线 · {args.baseline!r} 既不是目录也不在 git 检出里 · "
                        f"修法：给出目录路径或在一个 git 检出内运行"
                    )
                baseline_dir = _materialise_ref(root, args.baseline, Path(scratch) / "baseline")

        assert baseline_dir is not None  # narrowing for the type checker
        try:
            current_registry = load_vocabulary(current)
        except VocabularyError as exc:
            print(f"词表 · 结构 · 候选词表不合法：{exc} · 修法：先修结构错误，再比只增不减")
            return 1
        try:
            baseline_registry = load_vocabulary(baseline_dir)
        except VocabularyError as exc:
            # A broken baseline means no comparison happened: "unchecked" must not
            # look like "additive".
            _cannot_run(
                f"词表 · 基线 · 基线词表 {baseline_label!r} 不合法，本次未比对：{exc} · "
                f"修法：换一个合法的基线（已发布 tag 应始终通过结构校验）"
            )

        try:
            assert_additive(current, baseline_dir)
        except VocabularyError as exc:
            print(
                f"词表 · 只增不减 · 相对于 {baseline_label} 不是只增：{exc} · "
                f"修法：恢复被删/被改名的条目 id；退役请写 superseded_by，不要删除"
            )
            return 1

    added = _added_entries(current_registry, baseline_registry)
    print(
        f"PASS: 词表 {current_registry.version} 只增不减（相对 {baseline_label}，"
        f"新增 {len(added)} 条，删除 0 条）"
    )
    for kind, entry_id in added[:20]:
        print(f"  + {kind}/{entry_id}")
    if len(added) > 20:
        print(f"  … 另有 {len(added) - 20} 条")
    return 0


def _added_entries(current, baseline) -> list[tuple[str, str]]:
    """Entry ids present now and absent before, in file-kind then id order."""
    before = {
        (kind, entry.id) for kind, entries in baseline.entries.items() for entry in entries
    }
    return [
        (kind, entry.id)
        for kind, entries in current.entries.items()
        for entry in entries
        if (kind, entry.id) not in before
    ]


if __name__ == "__main__":
    raise SystemExit(main())
