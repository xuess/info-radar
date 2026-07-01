"""Shared pytest fixtures for InfoDigest tests."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
# Ensure infodigest importable when running from repo root
sys.path.insert(0, str(REPO_ROOT))

FIXTURES = REPO_ROOT / "tests" / "fixtures"


@pytest.fixture
def rss2_bytes() -> bytes:
    return (FIXTURES / "rss2_sample.xml").read_bytes()


@pytest.fixture
def atom_bytes() -> bytes:
    return (FIXTURES / "atom_sample.xml").read_bytes()


@pytest.fixture
def bad_feed_bytes() -> bytes:
    return (FIXTURES / "bad_feed.xml").read_bytes()


@pytest.fixture
def rss2_path() -> Path:
    return FIXTURES / "rss2_sample.xml"


@pytest.fixture
def atom_path() -> Path:
    return FIXTURES / "atom_sample.xml"


@pytest.fixture
def tmp_db(tmp_path) -> str:
    """A temporary SQLite db path that does not exist yet."""
    return str(tmp_path / "test.db")
