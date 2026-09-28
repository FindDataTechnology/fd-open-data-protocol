"""CLI for the unified indicator registry.

    python -m fd_open_data_protocol.registry_cli <command> ...

Commands:
  init-db     create the registry_entries table on the registry database
  register    map source rows through an adapter and batch-upsert (idempotent
              by native-code anchor; re-runs report "unchanged", new rows are
              counted as increments)
  verify      mark gate-passing entries verified (rule + printed sample)
  coverage    per-source registered/actual report (+ phase-2 visibility,
              + unmapped-by-module audit)
  export      dump entries to JSON (verified-only by default) for consumers
              (fd-open-data-mcp catalog, official-web db_stats)

DSN defaults come from $FD_REGISTRY_DSN (fd_open_data on the data machine)
and $FD_SOURCE_DSN (the source database being registered). ``--rows CSV``
replaces the source database entirely - tests and the shipped template
example run the full pipeline without any DB.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from fd_open_data_protocol.registry import (
    count_source_rows,
    coverage_report,
    fetch_rows,
    load_adapter,
    map_rows,
    read_rows_csv,
)
from fd_open_data_protocol.registry_store import (
    BaseRegistryStore,
    MemoryRegistryStore,
    PostgresRegistryStore,
)


def _registry_store(args: argparse.Namespace) -> BaseRegistryStore:
    if getattr(args, "dry_run", False):
        return MemoryRegistryStore()
    dsn = args.registry_dsn or os.environ.get("FD_REGISTRY_DSN")
    if not dsn:
        sys.exit("error: --registry-dsn or $FD_REGISTRY_DSN is required")
    return PostgresRegistryStore(dsn)


def _load_adapters(paths: list[str]):
    adapters = [load_adapter(p) for p in paths]
    for a in adapters:
        print(f"adapter: {a.source_db}.{a.source_table} (code column: {a.native_code_column})")
    return adapters


def _print_sample(store: BaseRegistryStore, source_db: str, sample: int) -> None:
    """The sampling half of the "rule + sample" verification record."""
    entries = [e for e in store.iter_entries(verified_only=True, source_db=source_db)]
    if not entries:
        print(f"verify sample [{source_db}]: no verified entries to sample")
        return
    picked = random.sample(entries, min(sample, len(entries)))
    print(f"verify sample [{source_db}] ({len(picked)}/{len(entries)} verified):")
    for e in picked:
        print(
            f"  {e.semantic_code}  |  {e.native_code}  |  zh={e.name_zh}  |  en={e.name_en}"
        )


def cmd_init_db(args: argparse.Namespace) -> int:
    store = _registry_store(args)
    store.init_schema()
    print("registry_entries table ready (CREATE TABLE IF NOT EXISTS applied)")
    return 0


def cmd_register(args: argparse.Namespace) -> int:
    store = _registry_store(args)
    adapters = _load_adapters(args.adapter)
    grand = {"new": 0, "updated": 0, "unchanged": 0, "demoted": 0}
    for adapter in adapters:
        if args.rows:
            rows = read_rows_csv(args.rows)
        else:
            dsn = args.source_dsn or os.environ.get("FD_SOURCE_DSN")
            if not dsn:
                sys.exit(
                    f"error: adapter {adapter.source_db}.{adapter.source_table} needs "
                    "--source-dsn or $FD_SOURCE_DSN (or --rows CSV)"
                )
            rows = fetch_rows(adapter, dsn)
        entries = map_rows(adapter, rows)
        stats = store.upsert_entries(entries)
        gate_passing = sum(
            1
            for e in entries
            if e.semantic_code and e.name_zh and e.name_en
        )
        verified_now = 0
        if args.auto_verify and not args.dry_run:
            verified_now = store.set_verified(
                source_db=adapter.source_db, verified_by=f"rule:naming-gate"
            )
        print(
            f"{adapter.source_db}.{adapter.source_table}: source_rows={len(rows)} "
            f"registered={stats.new} updated={stats.updated} unchanged={stats.unchanged} "
            f"demoted={stats.demoted} | gate_passing={gate_passing} "
            f"verified_now={verified_now}"
        )
        for key in grand:
            grand[key] += getattr(stats, key)
        if args.auto_verify and not args.dry_run:
            _print_sample(store, adapter.source_db, args.sample)
    print(json.dumps(grand, ensure_ascii=False))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    store = _registry_store(args)
    count = store.set_verified(
        source_db=args.source_db, verified_by=args.by or "rule:naming-gate"
    )
    print(f"newly verified: {count}" + (f" (source_db={args.source_db})" if args.source_db else ""))
    if args.source_db:
        _print_sample(store, args.source_db, args.sample)
    return 0


def cmd_coverage(args: argparse.Namespace) -> int:
    store = _registry_store(args)
    actual_counts: dict[str, int] = {}
    if args.actual_json:
        actual_counts = json.loads(Path(args.actual_json).read_text(encoding="utf-8"))
    elif args.adapter:
        for adapter in _load_adapters(args.adapter):
            dsn = args.source_dsn or os.environ.get("FD_SOURCE_DSN")
            if not dsn:
                sys.exit("error: coverage with --adapter needs --source-dsn or $FD_SOURCE_DSN")
            actual_counts[adapter.source_db] = count_source_rows(adapter, dsn)
    module_map = (
        json.loads(Path(args.module_map).read_text(encoding="utf-8"))
        if args.module_map
        else None
    )
    report = coverage_report(store, actual_counts, module_map=module_map)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"coverage report written: {args.out}")
    print(text)
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    store = _registry_store(args)
    entries = [
        e.model_dump()
        for e in store.iter_entries(verified_only=not args.all, source_db=args.source_db)
    ]
    payload = {
        "as_of": datetime.now().astimezone().isoformat(timespec="seconds"),
        "verified_only": not args.all,
        "count": len(entries),
        "entries": entries,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"exported {len(entries)} entries -> {args.out}")
    else:
        print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fd-registry", description="Unified indicator registry CLI"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser, registry: bool = True) -> None:
        if registry:
            p.add_argument("--registry-dsn", help="registry DB DSN (default $FD_REGISTRY_DSN)")
        p.add_argument("--dry-run", action="store_true", help="use in-memory store, write nothing")

    p = sub.add_parser("init-db", help="create registry_entries")
    common(p)
    p.set_defaults(func=cmd_init_db)

    p = sub.add_parser("register", help="batch-register one or more adapters")
    common(p)
    p.add_argument("--adapter", action="append", required=True, help="adapter YAML (repeatable)")
    p.add_argument("--source-dsn", help="source DB DSN (default $FD_SOURCE_DSN)")
    p.add_argument("--rows", help="CSV rows file instead of a live source DB")
    p.add_argument("--auto-verify", action="store_true",
                   help="after upsert, verify all gate-passing entries (rule:naming-gate)")
    p.add_argument("--sample", type=int, default=5, help="sample size printed as verify record")
    p.set_defaults(func=cmd_register)

    p = sub.add_parser("verify", help="mark gate-passing entries verified")
    common(p)
    p.add_argument("--source-db", help="restrict to one source_db")
    p.add_argument("--by", help="verification record (default rule:naming-gate)")
    p.add_argument("--sample", type=int, default=5)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("coverage", help="registered/actual coverage report")
    common(p)
    p.add_argument("--adapter", action="append", help="adapter(s) to count actual source rows")
    p.add_argument("--source-dsn", help="source DB DSN for actual counts")
    p.add_argument("--actual-json", help="JSON {source_db: count} instead of live counts")
    p.add_argument("--module-map", help="JSON module map for unmapped audit")
    p.add_argument("--out", help="also write the report to this file")
    p.set_defaults(func=cmd_coverage)

    p = sub.add_parser("export", help="dump entries (verified-only by default)")
    common(p)
    p.add_argument("--out", help="output JSON file (default stdout)")
    p.add_argument("--all", action="store_true", help="include unverified entries")
    p.add_argument("--source-db", help="restrict to one source_db")
    p.set_defaults(func=cmd_export)

    return parser


def main(argv: Optional[list] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
