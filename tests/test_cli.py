"""Tests for cli.py — subcommand dispatch and basic output."""
from __future__ import annotations

from pathlib import Path

import pytest

from infodigest.cli import build_parser, main


class TestParser:
    def test_run_command(self):
        parser = build_parser()
        args = parser.parse_args(["run"])
        assert args.command == "run"

    def test_collect_command(self):
        parser = build_parser()
        args = parser.parse_args(["collect"])
        assert args.command == "collect"

    def test_report_command(self):
        parser = build_parser()
        args = parser.parse_args(["report"])
        assert args.command == "report"

    def test_sources_command(self):
        parser = build_parser()
        args = parser.parse_args(["sources"])
        assert args.command == "sources"

    def test_health_command(self):
        parser = build_parser()
        args = parser.parse_args(["health", "--days", "14"])
        assert args.command == "health"
        assert args.days == 14

    def test_adjust_command(self):
        parser = build_parser()
        args = parser.parse_args(["adjust", "--base", "0.8", "--recent", "0.2"])
        assert args.command == "adjust"
        assert args.base == 0.8
        assert args.recent == 0.2

    def test_db_override(self):
        parser = build_parser()
        args = parser.parse_args(["--db", "/tmp/x.db", "run"])
        assert args.db == "/tmp/x.db"

    def test_missing_command_errors(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])


class TestSourcesCommand:
    def test_sources_lists_all(self, capsys):
        rc = main(["sources"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "hackernews" in out
        assert "ruanyifeng" in out

    def test_report_no_runs(self, tmp_db, capsys):
        rc = main(["--db", tmp_db, "report"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "No runs" in out

    def test_report_with_runs_and_stats(self, tmp_db, capsys):
        from infodigest.storage.models import init_db
        from infodigest.storage.repo import Repo
        conn = init_db(tmp_db)
        repo = Repo(conn)
        rid = repo.start_run()
        repo.finish_run(rid, collected=10, deduped=2, rated=8, delivered=8, status="ok")
        repo.create_digest("feishu", 5, status="sent")
        repo.create_digest("dingtalk", 3, status="sent")
        conn.close()
        rc = main(["--db", tmp_db, "report"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "7-day stats" in out
        assert "collected: 10" in out
        assert "feishu" in out
        assert "dingtalk" in out

    def test_health_command(self, tmp_db, capsys):
        from infodigest.storage.models import init_db
        from infodigest.storage.repo import Repo
        from infodigest.config import Source
        conn = init_db(tmp_db)
        repo = Repo(conn)
        repo.upsert_source(Source(id="hn", url="https://x", authority=0.9, tags=("n",)))
        conn.close()
        rc = main(["--db", tmp_db, "health"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "hn" in out
        assert "auth" in out

    def test_adjust_command(self, tmp_db, capsys):
        from infodigest.storage.models import init_db
        from infodigest.storage.repo import Repo
        from infodigest.config import Source
        conn = init_db(tmp_db)
        repo = Repo(conn)
        repo.upsert_source(Source(id="hn", url="https://x", authority=0.9, tags=("n",)))
        conn.close()
        rc = main(["--db", tmp_db, "adjust", "--base", "0.8", "--recent", "0.2"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Adjusted" in out

    def test_health_empty(self, tmp_db, capsys):
        rc = main(["--db", tmp_db, "health"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "No sources" in out


class TestCollectCommand:
    def test_collect_with_file_source(self, tmp_db, monkeypatch, capsys):
        # Patch fetch to read local fixture
        from infodigest.collector.fetcher import FetchResult
        import infodigest.cli as cli_mod
        import infodigest.collector.fetcher as fetcher_mod

        fixtures = Path(__file__).parent / "fixtures"
        content = (fixtures / "rss2_sample.xml").read_bytes()

        # We need the config source url to be file:// and patch the fetch used in cmd_collect
        # cmd_collect imports fetch directly, so patch fetcher_mod.fetch
        def fake_fetch(url, cfg, etag=None, last_modified=None):
            return FetchResult(content=content, status=200, url=url)

        monkeypatch.setattr(fetcher_mod, "fetch", fake_fetch)

        # Temporarily override config to use file:// source
        import infodigest.config as cfg_mod
        orig_load = cfg_mod.load_config

        def fake_load_config(config_dir=None):
            c = orig_load(config_dir)
            # Replace sources with a file:// source
            from infodigest.config import Source
            new_src = Source(id="fixture", url="file://fake", category="tech", authority=0.8, lang="en", tags=("t",), enabled=True)
            return cfg_mod.Config(
                sources=(new_src,),
                collect=c.collect, delivery=c.delivery, storage=c.storage,
                schedule=c.schedule, rater=c.rater, config_dir=c.config_dir,
            )

        monkeypatch.setattr(cfg_mod, "load_config", fake_load_config)
        monkeypatch.setattr(cli_mod, "load_config", fake_load_config)

        rc = main(["--db", tmp_db, "collect"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "fixture" in out


class TestRunCommand:
    def test_run_with_mocked_pipeline(self, tmp_db, monkeypatch, capsys):
        import infodigest.cli as cli_mod
        from infodigest.scheduler.runner import RunReport

        def fake_run(config, db_path=None, feishu=None, dingtalk=None):
            r = RunReport()
            r.collected = 5
            r.deduped = 1
            r.rated = 4
            r.stored = 4
            r.delivered = 2
            r.run_id = 42
            return r

        monkeypatch.setattr(cli_mod, "run", fake_run, raising=False)
        # Also patch the runner module's run since cmd_run imports it locally
        import infodigest.scheduler.runner as runner_mod
        monkeypatch.setattr(runner_mod, "run", fake_run)

        rc = main(["--db", tmp_db, "run"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Run #42" in out
        assert "collected=5" in out
        assert "delivered=2" in out

    def test_run_with_errors_returns_nonzero(self, tmp_db, monkeypatch, capsys):
        import infodigest.scheduler.runner as runner_mod
        from infodigest.scheduler.runner import RunReport

        def fake_run(config, db_path=None, feishu=None, dingtalk=None):
            r = RunReport()
            r.run_id = 7
            r.collected = 3
            r.errors.append("webhook down")
            return r

        monkeypatch.setattr(runner_mod, "run", fake_run)
        rc = main(["--db", tmp_db, "run"])
        assert rc == 1
        out = capsys.readouterr().out
        assert "errors" in out
        assert "webhook down" in out


class TestCollectEdgeCases:
    def test_collect_304_path(self, tmp_db, monkeypatch, capsys):
        from infodigest.collector.fetcher import FetchResult
        import infodigest.cli as cli_mod
        import infodigest.config as cfg_mod
        from infodigest.config import Source

        def fake_fetch(url, cfg, etag=None, last_modified=None):
            return FetchResult(content=b"", status=304, not_modified=True, url=url)

        monkeypatch.setattr("infodigest.collector.fetcher.fetch", fake_fetch)
        orig_load = cfg_mod.load_config
        def fake_load_config(config_dir=None):
            c = orig_load(config_dir)
            src = Source(id="fixture", url="file://fake", category="tech", authority=0.8, tags=("t",), enabled=True)
            return cfg_mod.Config(sources=(src,), collect=c.collect, delivery=c.delivery, storage=c.storage, schedule=c.schedule, rater=c.rater, config_dir=c.config_dir)
        monkeypatch.setattr(cfg_mod, "load_config", fake_load_config)
        monkeypatch.setattr(cli_mod, "load_config", fake_load_config)
        rc = main(["--db", tmp_db, "collect"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "[304]" in out

    def test_collect_fetch_error_path(self, tmp_db, monkeypatch, capsys):
        from infodigest.collector.fetcher import FetchError
        import infodigest.cli as cli_mod
        import infodigest.config as cfg_mod
        from infodigest.config import Source

        def fake_fetch(url, cfg, etag=None, last_modified=None):
            raise FetchError("fetch failed: HTTP 500")

        monkeypatch.setattr("infodigest.collector.fetcher.fetch", fake_fetch)
        orig_load = cfg_mod.load_config
        def fake_load_config(config_dir=None):
            c = orig_load(config_dir)
            src = Source(id="fixture", url="file://fake", category="tech", authority=0.8, tags=("t",), enabled=True)
            return cfg_mod.Config(sources=(src,), collect=c.collect, delivery=c.delivery, storage=c.storage, schedule=c.schedule, rater=c.rater, config_dir=c.config_dir)
        monkeypatch.setattr(cfg_mod, "load_config", fake_load_config)
        monkeypatch.setattr(cli_mod, "load_config", fake_load_config)
        rc = main(["--db", tmp_db, "collect"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "[FAIL]" in out
        assert "Total new entries: 0" in out
