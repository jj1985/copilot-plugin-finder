"""SQLite schema and small helpers. Schema follows PLAN.md §4.3 (v2)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS repo (
  id INTEGER PRIMARY KEY,              -- GitHub databaseId
  node_id TEXT UNIQUE,
  full_name TEXT NOT NULL,
  owner TEXT, owner_type TEXT, owner_id INTEGER,
  description TEXT, homepage TEXT,
  stars INTEGER, forks INTEGER,
  created_at TEXT, pushed_at TEXT, committed_at TEXT, archived_at TEXT,
  is_fork INTEGER DEFAULT 0, parent_full_name TEXT, parent_id INTEGER,
  template_full_name TEXT, template_id INTEGER,
  is_archived INTEGER DEFAULT 0, is_template INTEGER DEFAULT 0, is_mirror INTEGER DEFAULT 0, is_empty INTEGER DEFAULT 0,
  default_branch TEXT, license TEXT, language TEXT, latest_release TEXT, latest_release_at TEXT,
  head_oid TEXT, root_tree_oid TEXT, readme_name TEXT, readme_oid TEXT, readme_excerpt TEXT,
  kind TEXT, native_level TEXT, evidence TEXT, format TEXT,
  dual_format INTEGER DEFAULT 0, copilot_specific INTEGER DEFAULT 0,
  executes_code TEXT, surfaces TEXT,
  effective_marketplace_path TEXT, effective_plugin_path TEXT, shadowed_manifests TEXT, misplaced_manifest INTEGER DEFAULT 0,
  marketplace_name TEXT, marketplace_owner_name TEXT, marketplace_description TEXT, marketplace_version TEXT, plugin_root TEXT,
  plugin_name TEXT, plugin_version TEXT, plugin_description TEXT,
  plugin_count INTEGER DEFAULT 0, external_plugin_count INTEGER DEFAULT 0,
  skill_count INTEGER, agent_count INTEGER, hook_count INTEGER, mcp_count INTEGER, lsp_count INTEGER, extension_count INTEGER,
  schema_valid INTEGER, schema_warnings TEXT,
  referenced_by_marketplaces INTEGER DEFAULT 0, referenced_by_settings INTEGER DEFAULT 0, listed_by_seed TEXT,
  cluster_id INTEGER, is_canonical INTEGER DEFAULT 1, network_size INTEGER, indexed_copies INTEGER, diverged_fork INTEGER DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'candidate',   -- candidate|active|demarked|gone|renamed|unindexed|inaccessible
  first_seen TEXT NOT NULL, last_verified TEXT, last_seen_in_search TEXT, missing_since TEXT,
  marker_version INTEGER
);
CREATE INDEX IF NOT EXISTS repo_full_name ON repo(full_name);
CREATE INDEX IF NOT EXISTS repo_status ON repo(status);

CREATE TABLE IF NOT EXISTS repo_topic (repo_id INTEGER NOT NULL, topic TEXT NOT NULL, PRIMARY KEY (repo_id, topic));

CREATE TABLE IF NOT EXISTS repo_state (
  repo_id INTEGER PRIMARY KEY, head_oid TEXT, root_tree_oid TEXT, verified_at TEXT, v2_done INTEGER DEFAULT 0,
  root_entries TEXT, dir_entries TEXT, paths TEXT
);

CREATE TABLE IF NOT EXISTS blob (
  oid TEXT PRIMARY KEY, byte_size INTEGER, text TEXT, parsed_json TEXT, parse_error TEXT,
  owner_count INTEGER DEFAULT 0, is_template_blob INTEGER DEFAULT 0, first_seen TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS manifest_history (
  repo_id INTEGER NOT NULL, path TEXT NOT NULL, blob_oid TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
  PRIMARY KEY (repo_id, path, blob_oid)
);

CREATE TABLE IF NOT EXISTS marker_hit (
  repo_id INTEGER NOT NULL, marker_id TEXT NOT NULL, path TEXT NOT NULL,
  blob_oid TEXT, is_root INTEGER DEFAULT 1, is_fork INTEGER DEFAULT 0,
  first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
  PRIMARY KEY (repo_id, marker_id, path)
);

CREATE TABLE IF NOT EXISTS plugin (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  repo_id INTEGER NOT NULL, name TEXT NOT NULL, version TEXT, description TEXT,
  source_kind TEXT, source_host TEXT, source_repo TEXT, source_repo_id INTEGER, source_path TEXT, ref TEXT, sha TEXT, pinned INTEGER DEFAULT 0,
  keywords TEXT, category TEXT, tags TEXT, strict INTEGER, format TEXT, dir_tree_oid TEXT,
  skill_count INTEGER, agent_count INTEGER, hook_count INTEGER, mcp_count INTEGER, executes_code TEXT,
  UNIQUE (repo_id, name)
);

CREATE TABLE IF NOT EXISTS plugin_ref (
  marketplace_repo_id INTEGER NOT NULL, entry_name TEXT NOT NULL, target_repo TEXT NOT NULL, target_repo_id INTEGER,
  target_path TEXT, ref TEXT, sha TEXT, PRIMARY KEY (marketplace_repo_id, entry_name)
);

CREATE TABLE IF NOT EXISTS skill (
  plugin_id INTEGER NOT NULL, name TEXT NOT NULL, description TEXT, path TEXT, blob_oid TEXT, PRIMARY KEY (plugin_id, path)
);

CREATE TABLE IF NOT EXISTS adopter (
  repo_id INTEGER NOT NULL, marketplace_ref TEXT NOT NULL, file_path TEXT NOT NULL, enabled_plugins TEXT,
  PRIMARY KEY (repo_id, marketplace_ref, file_path)
);

CREATE TABLE IF NOT EXISTS edge (
  repo_a INTEGER NOT NULL, repo_b INTEGER NOT NULL, signal TEXT NOT NULL, evidence TEXT, created_at TEXT NOT NULL,
  PRIMARY KEY (repo_a, repo_b, signal)
);

CREATE TABLE IF NOT EXISTS cluster_override (id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT, repo_ids TEXT, reason TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS template_blob (oid TEXT PRIMARY KEY, owner_count INTEGER, reason TEXT);
CREATE TABLE IF NOT EXISTS deny (key TEXT PRIMARY KEY, reason TEXT, created_at TEXT);

CREATE TABLE IF NOT EXISTS referral (
  full_name_lc TEXT NOT NULL, kind TEXT NOT NULL, from_repo_id INTEGER, path TEXT, first_seen TEXT NOT NULL,
  PRIMARY KEY (full_name_lc, kind, from_repo_id, path)
);
CREATE INDEX IF NOT EXISTS referral_name ON referral(full_name_lc);

CREATE TABLE IF NOT EXISTS cluster (
  id INTEGER PRIMARY KEY, canonical_repo_id INTEGER NOT NULL, size INTEGER, fork_members INTEGER, clone_members INTEGER, computed_at TEXT
);

CREATE TABLE IF NOT EXISTS slice_run (
  scan_id INTEGER NOT NULL, family TEXT NOT NULL, query TEXT NOT NULL,
  pages_fetched INTEGER, items INTEGER, accepted INTEGER, total_count INTEGER,
  last_page_short INTEGER, incomplete_results INTEGER, over_cap INTEGER, completed_at TEXT,
  PRIMARY KEY (scan_id, family, query)
);

CREATE TABLE IF NOT EXISTS scan (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, started TEXT NOT NULL, finished TEXT, status TEXT,
  requests_used TEXT, repos_seen INTEGER, repos_verified INTEGER, errors TEXT, recall_golden REAL, notes TEXT
);

CREATE TABLE IF NOT EXISTS scan_diff (scan_id INTEGER NOT NULL, repo_id INTEGER NOT NULL, change TEXT NOT NULL, detail TEXT);

CREATE TABLE IF NOT EXISTS repo_snapshot (repo_id INTEGER NOT NULL, date TEXT NOT NULL, stars INTEGER, forks INTEGER, PRIMARY KEY (repo_id, date));
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=OFF")
    migrate(conn)
    return conn


ADDED_COLUMNS = {
    "repo_state": [("root_entries", "TEXT"), ("dir_entries", "TEXT"), ("paths", "TEXT")],
}


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for table, cols in ADDED_COLUMNS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, typ in cols:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
    row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    if row["v"] is None or row["v"] < SCHEMA_VERSION:
        conn.execute("INSERT OR REPLACE INTO schema_version(version, applied_at) VALUES (?, ?)", (SCHEMA_VERSION, now()))
    conn.commit()


def j(value: Any) -> str | None:
    """JSON-encode for a TEXT column; None stays None."""
    return None if value is None else json.dumps(value, ensure_ascii=False, sort_keys=True)


def upsert(conn: sqlite3.Connection, table: str, row: dict[str, Any], key: Iterable[str]) -> None:
    cols = list(row.keys())
    keys = list(key)
    placeholders = ",".join("?" for _ in cols)
    updates = ",".join(f"{c}=excluded.{c}" for c in cols if c not in keys)
    sql = f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})"
    if updates:
        sql += f" ON CONFLICT({','.join(keys)}) DO UPDATE SET {updates}"
    else:
        sql += f" ON CONFLICT({','.join(keys)}) DO NOTHING"
    conn.execute(sql, [row[c] for c in cols])


def start_scan(conn: sqlite3.Connection, kind: str) -> int:
    cur = conn.execute("INSERT INTO scan(kind, started, status) VALUES (?, ?, 'running')", (kind, now()))
    conn.commit()
    return int(cur.lastrowid)


def finish_scan(conn: sqlite3.Connection, scan_id: int, status: str, **fields: Any) -> None:
    sets = ", ".join(f"{k}=?" for k in fields)
    vals = [j(v) if isinstance(v, (dict, list)) else v for v in fields.values()]
    conn.execute(
        f"UPDATE scan SET finished=?, status=?{', ' + sets if sets else ''} WHERE id=?",
        [now(), status, *vals, scan_id],
    )
    conn.commit()
