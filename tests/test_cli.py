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
