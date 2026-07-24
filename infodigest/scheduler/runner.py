"""Scheduler runner: orchestrate collect → rate → curate → store → deliver.

The runner ties all modules together. It is the single entry point invoked
by CLI and GitHub Actions. Returns a RunReport with per-stage counts.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..collector.dedup import dedup_cross_source, dedup_entries
from ..collector.fetcher import FetchError, fetch
from ..collector.parser import Entry, parse
from ..config import Config, Source
from ..delivery.base import SendResult
from ..formatter.builder import render_dingtalk, render_feishu
from ..rater.curator import curate
from ..rater.event_history import (
    EventHistory,
    get_daily_push_state,
    update_daily_push_state,
)
from ..rater.scorer import ScoreContext, score
from ..storage.models import init_db
from ..storage.repo import Repo

log = logging.getLogger(__name__)


@dataclass
class RunReport:
    """Summary of a single pipeline run."""

    collected: int = 0
    deduped: int = 0
    rated: int = 0
    curated: int = 0
    stored: int = 0
    delivered: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    sources_ok: int = 0
    sources_failed: int = 0
    run_id: int = 0
    silent: bool = False

    @property
    def status(self) -> str:
        return "ok" if not self.errors else "partial"


def _collect_one(source: Source, config: Config, repo: Repo) -> list[Entry]:
    """Fetch + parse a single source. Returns entries (empty on failure)."""
    repo.upsert_source(source)
    etag, last_mod = repo.get_source_cache(source.id)
    try:
        result = fetch(source.url, config.collect, etag=etag, last_modified=last_mod)
    except FetchError as exc:
        log.warning("fetch failed for %s: %s", source.id, exc)
        repo.disable_source(source.id)
        return []
    if result.not_modified:
        log.info("source %s not modified (304)", source.id)
        repo.upsert_source(source)
        return []
    repo.upsert_source(source, etag=result.etag, last_modified=result.last_modified)
    entries = parse(result.content, source)
    for e in entries:
        e.raw["authority"] = source.authority
        e.raw["category"] = source.category
        e.raw["tags"] = list(source.tags)
    return entries


def _deliver(channel, messages, repo: Repo, digest_ids: list[str], failed_dir: str) -> tuple[int, int, list[str]]:
    """Send rendered messages via a channel. Returns (ok, failed, errors)."""
    ok = 0
    failed = 0
    errors: list[str] = []
    for msg in messages:
        result: SendResult = channel.send(msg.content)
        if result.ok:
            ok += 1
        else:
            failed += 1
            errors.append(f"{channel.name} batch {msg.batch_index}: {result.error}")
            from ..delivery.failed_digests import save_failed

            digest_id = digest_ids[msg.batch_index] if msg.batch_index < len(digest_ids) else ""
            save_failed(
                failed_dir, channel.name, msg.content, msg.entry_count,
                msg.batch_index, result.error or "unknown", digest_id,
            )
    return ok, failed, errors


def _source_meta(config: Config) -> dict[str, tuple[str, tuple[str, ...]]]:
    return {s.id: (s.category, s.tags) for s in config.sources}


def run(config: Config, db_path: str | None = None, feishu=None, dingtalk=None) -> RunReport:
    """Run the full pipeline: collect → dedup → rate → curate → store → deliver.

    Args:
        config: loaded Config.
        db_path: override storage db path (defaults to config.storage.db_path).
        feishu: injected FeishuChannel (for testing); created from env if None.
        dingtalk: injected DingTalkChannel (for testing); created from env if None.

    Returns RunReport.
    """
    report = RunReport()
    db = db_path or config.storage.db_path
    conn = init_db(db)
    repo = Repo(conn)
    history = EventHistory(conn, config.rater)
    run_id = repo.start_run()
    report.run_id = run_id

    all_entries: list[Entry] = []
    try:
        # ---- COLLECT ----
        for source in config.enabled_sources:
            entries = _collect_one(source, config, repo)
            if entries:
                report.sources_ok += 1
            all_entries.extend(entries)
        report.collected = len(all_entries)

        # ---- DEDUP (within batch + cross-source) ----
        recent = repo.recent_titles(config.rater.dedup_window_days)
        deduped_entries, dropped1 = dedup_entries(
            all_entries,
            recent_titles=recent,
            similarity_threshold=config.rater.dedup_similarity,
        )
        deduped_entries, dropped2 = dedup_cross_source(
            deduped_entries,
            similarity_threshold=config.rater.dedup_similarity,
        )
        report.deduped = dropped1 + dropped2

        # ---- STORE (new entries) ----
        stored = repo.upsert_entries(deduped_entries)
        report.stored = stored

        # ---- RATE (with decay/novelty from history) ----
        decay_by_uid: dict[str, float] = {}
        novelty_by_uid: dict[str, float] = {}
        for e in deduped_entries:
            # Hint grade from event tier alone for decay rate lookup
            from ..rater.scorer import score_event_tier

            tier = score_event_tier(e.title, e.summary, config.rater)
            decay_info = history.compute_decay(
                e.title,
                grade_hint=tier.tier,
                text_for_novelty=f"{e.title} {e.summary or ''}",
            )
            decay_by_uid[e.uid] = decay_info.decay
            novelty_by_uid[e.uid] = decay_info.novelty

        ctx = ScoreContext.build(
            config.rater,
            recent_titles=recent,
            decay_by_uid=decay_by_uid,
            novelty_by_uid=novelty_by_uid,
            source_meta=_source_meta(config),
        )
        scored = []
        for e in deduped_entries:
            se = score(e, ctx)
            repo.update_score(se)
            scored.append(se)
        report.rated = len(scored)

        # ---- CURATE (quality gate + quotas) ----
        pending = repo.pending_digest(config.delivery.push_grade_min)
        # Enrich pending with source meta for display (already scored in DB)
        for e in pending:
            meta = _source_meta(config).get(e.source_id)
            if meta:
                e.raw.setdefault("category", meta[0])
                e.raw.setdefault("tags", list(meta[1]))

        daily = get_daily_push_state(conn)
        curated = curate(
            pending,
            config.rater,
            history=history,
            daily_state=daily,
        )
        report.curated = len(curated.entries)
        report.silent = curated.silent

        if not curated.entries:
            log.info(
                "no curated entries to deliver (silent=%s, reasons=%s)",
                curated.silent,
                curated.reasons,
            )
        else:
            if feishu is None and config.delivery.feishu_enabled:
                from ..delivery.feishu import FeishuChannel

                feishu = FeishuChannel(delivery=config.delivery)
            if dingtalk is None and config.delivery.dingtalk_enabled:
                from ..delivery.dingtalk import DingTalkChannel

                dingtalk = DingTalkChannel(delivery=config.delivery)

            to_push = curated.entries
            sources_list = list({e.source_id for e in to_push})
            source_langs = {src.id: src.lang for src in config.sources}
            failed_dir = config.storage.failed_digests_dir
            if not Path(failed_dir).is_absolute():
                failed_dir = str(Path(db).parent / "failed_digests")

            delivered = 0
            failures = 0
            errors: list[str] = []

            if feishu is not None:
                msgs = render_feishu(
                    to_push,
                    sources=sources_list,
                    delivery=config.delivery,
                    translate_cfg=config.translate,
                    source_langs=source_langs,
                )
                digest_ids = [repo.create_digest("feishu", m.entry_count) for m in msgs]
                ok, fail, errs = _deliver(feishu, msgs, repo, digest_ids, failed_dir)
                delivered += ok
                failures += fail
                errors.extend(errs)
                if digest_ids:
                    repo.mark_entries_digest([e.uid for e in to_push], digest_ids[0])

            if dingtalk is not None:
                msgs = render_dingtalk(
                    to_push,
                    sources=sources_list,
                    delivery=config.delivery,
                    translate_cfg=config.translate,
                    source_langs=source_langs,
                )
                digest_ids = [repo.create_digest("dingtalk", m.entry_count) for m in msgs]
                ok, fail, errs = _deliver(dingtalk, msgs, repo, digest_ids, failed_dir)
                delivered += ok
                failures += fail
                errors.extend(errs)

            report.delivered = delivered
            report.failed = failures
            report.errors.extend(errors)

            # Record history + daily quotas only after at least one successful send
            if delivered > 0:
                history.record_many(
                    [e.title for e in to_push],
                    [float(e.raw.get("raw_score", 50)) for e in to_push],
                )
                update_daily_push_state(
                    conn, [str(e.raw.get("grade", e.grade)) for e in to_push]
                )
                history.cleanup()

        report.sources_failed = len(config.enabled_sources) - report.sources_ok
        repo.finish_run(
            run_id,
            collected=report.collected,
            deduped=report.deduped,
            rated=report.rated,
            delivered=report.delivered,
            status=report.status,
        )
    except Exception as exc:
        log.exception("pipeline run failed")
        report.errors.append(str(exc))
        repo.finish_run(run_id, status="error")
    finally:
        conn.close()

    return report
