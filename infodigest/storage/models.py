"""Storage models: SQLite schema + migration.

Tables: sources, entries, digests, runs. Idempotent CREATE IF NOT EXISTS.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY,
  url TEXT NOT NULL UNIQUE,
  category TEXT,
  lang TEXT,
  authority REAL DEFAULT 0.5,
  tags TEXT,
  etag TEXT,
  last_modified TEXT,
  enabled INTEGER DEFAULT 1,
  created_at TEXT
);

CREATE TABLE IF NOT EXISTS entries (
  uid TEXT PRIMARY KEY,
  source_id TEXT,
  title TEXT,
  summary TEXT,
  link TEXT,
  published TEXT,
  raw_score REAL,
  grade TEXT,
  engagement INTEGER,
  digest_id TEXT,
  created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_entries_published ON entries(published);
CREATE INDEX IF NOT EXISTS idx_entries_grade ON entries(grade);
CREATE INDEX IF NOT EXISTS idx_entries_source ON entries(source_id);

CREATE TABLE IF NOT EXISTS digests (
  id TEXT PRIMARY KEY,
  created_at TEXT,
  channel TEXT,
  entry_count INTEGER,
  status TEXT,
  error TEXT
);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT,
  ended_at TEXT,
  collected INTEGER,
  deduped INTEGER,
  rated INTEGER,
  delivered INTEGER,
  status TEXT
);

CREATE TABLE IF NOT EXISTS event_history (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  count INTEGER DEFAULT 1,
  last_score REAL DEFAULT 0,
  has_new_development INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_event_history_last_seen ON event_history(last_seen);

CREATE TABLE IF NOT EXISTS daily_push_state (
  date TEXT PRIMARY KEY,
  s_count INTEGER DEFAULT 0,
  a_count INTEGER DEFAULT 0,
  b_count INTEGER DEFAULT 0,
  updated_at TEXT
);
"""


def connect(db_path: str) -> sqlite3.Connection:
    """Open a SQLite connection with WAL + sane defaults. Creates parent dir."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """Apply schema (idempotent)."""
    conn.executescript(SCHEMA)
    conn.commit()


def init_db(db_path: str) -> sqlite3.Connection:
    """Connect + migrate. Returns ready-to-use connection."""
    conn = connect(db_path)
    migrate(conn)
    return conn
