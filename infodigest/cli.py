"""CLI entry point: collect / rate / deliver / run / report subcommands.

Usage:
  python -m infodigest.cli run          # full pipeline
  python -m infodigest.cli collect      # fetch+parse only
  python -m infodigest.cli report       # show recent run stats
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import REPO_ROOT, load_config


def cmd_run(args) -> int:
    from .scheduler.runner import run

    config = load_config()
    db = args.db or config.storage.db_path
    report = run(config, db_path=db)
    print(f"Run #{report.run_id}: {report.status}")
    print(f"  collected={report.collected} deduped={report.deduped} rated={report.rated}")
    print(f"  stored={report.stored} delivered={report.delivered} failed={report.failed}")
    if report.errors:
        print(f"  errors ({len(report.errors)}):")
        for e in report.errors[:10]:
            print(f"    - {e}")
    return 0 if report.status == "ok" else 1


def cmd_collect(args) -> int:
    from .collector.fetcher import FetchError, fetch
    from .collector.parser import parse
    from .storage.models import init_db
    from .storage.repo import Repo

    config = load_config()
    db = args.db or config.storage.db_path
    conn = init_db(db)
    repo = Repo(conn)
    total = 0
    for source in config.enabled_sources:
        etag, lm = repo.get_source_cache(source.id)
        try:
            result = fetch(source.url, config.collect, etag=etag, last_modified=lm)
        except FetchError as exc:
            print(f"  [FAIL] {source.id}: {exc}")
            continue
        if result.not_modified:
            print(f"  [304] {source.id}")
            repo.upsert_source(source)
            continue
        repo.upsert_source(source, etag=result.etag, last_modified=result.last_modified)
        entries = parse(result.content, source)
        n = repo.upsert_entries(entries)
        total += n
        print(f"  [OK]  {source.id}: {n} new entries")
    conn.close()
    print(f"Total new entries: {total}")
    return 0


def cmd_report(args) -> int:
    from .storage.models import init_db

    config = load_config()
    db = args.db or config.storage.db_path
    conn = init_db(db)
    rows = conn.execute(
        "SELECT * FROM runs ORDER BY id DESC LIMIT 10"
    ).fetchall()
    if not rows:
        print("No runs recorded yet.")
        conn.close()
        return 0
    print(f"{'id':>4} {'started':<26} {'col':>5} {'ded':>5} {'rat':>5} {'del':>5} {'status':<10}")
    for r in rows:
        print(f"{r['id']:>4} {r['started_at'] or '':<26} {r['collected']:>5} {r['deduped']:>5} {r['rated']:>5} {r['delivered']:>5} {r['status'] or '':<10}")
    conn.close()
    return 0


def cmd_sources(args) -> int:
    config = load_config()
    print(f"{'id':<20} {'category':<12} {'auth':>5} {'lang':<5} {'enabled':<8} url")
    for s in config.sources:
        print(f"{s.id:<20} {s.category:<12} {s.authority:>5} {s.lang:<5} {str(s.enabled):<8} {s.url}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="info-digest", description="InfoDigest RSS aggregator CLI")
    p.add_argument("--db", help="override SQLite db path")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("run", help="full pipeline: collect -> rate -> deliver").set_defaults(func=cmd_run)
    sub.add_parser("collect", help="fetch + parse only").set_defaults(func=cmd_collect)
    sub.add_parser("report", help="show recent run stats").set_defaults(func=cmd_report)
    sub.add_parser("sources", help="list configured sources").set_defaults(func=cmd_sources)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    level = logging.DEBUG if getattr(args, "verbose", False) else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
