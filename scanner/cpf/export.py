"""Export JSON for the (future) static site and for ad-hoc analysis."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .db import now

REPO_COLUMNS = [
    "id", "full_name", "owner", "owner_type", "description", "homepage", "stars", "forks",
    "created_at", "pushed_at", "committed_at", "is_fork", "parent_full_name", "template_full_name",
    "is_archived", "is_template", "default_branch", "license", "language", "latest_release",
    "kind", "native_level", "evidence", "format", "dual_format", "copilot_specific", "executes_code",
    "effective_marketplace_path", "effective_plugin_path", "shadowed_manifests",
    "marketplace_name", "marketplace_description", "plugin_name", "plugin_description",
    "plugin_count", "external_plugin_count", "schema_valid", "schema_warnings",
    "readme_excerpt", "status", "first_seen", "last_verified",
    "cluster_id", "is_canonical", "network_size", "indexed_copies", "diverged_fork",
    "referenced_by_marketplaces", "referenced_by_settings", "listed_by_seed",
]
JSON_COLUMNS = {"executes_code", "shadowed_manifests", "schema_warnings"}


def _rows(conn: sqlite3.Connection, sql: str, params=()) -> list[dict]:
    out = []
    for r in conn.execute(sql, params):
        d = dict(r)
        for c in JSON_COLUMNS & d.keys():
            if d[c]:
                try:
                    d[c] = json.loads(d[c])
                except ValueError:
                    pass
        out.append(d)
    return out


def export_all(conn: sqlite3.Connection, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    cols = ", ".join(REPO_COLUMNS)
    repos = _rows(conn, f"SELECT {cols} FROM repo WHERE status IN ('active','invalid') ORDER BY stars DESC, full_name")
    topics = {}
    for r in conn.execute("SELECT repo_id, topic FROM repo_topic"):
        topics.setdefault(r["repo_id"], []).append(r["topic"])
    markers = {}
    for r in conn.execute("SELECT repo_id, marker_id, path FROM marker_hit"):
        markers.setdefault(r["repo_id"], []).append({"marker": r["marker_id"], "path": r["path"]})
    for r in repos:
        r["topics"] = topics.get(r["id"], [])
        r["markers"] = markers.get(r["id"], [])
    plugins = _rows(conn, """SELECT p.repo_id, r.full_name AS repo, p.name, p.version, p.description, p.source_kind, p.source_repo, p.source_path,
                                    p.ref, p.sha, p.pinned, p.category, p.format, p.executes_code
                             FROM plugin p JOIN repo r ON r.id=p.repo_id WHERE r.status='active' ORDER BY r.stars DESC, p.name""")
    scan = conn.execute("SELECT * FROM scan ORDER BY id DESC LIMIT 1").fetchone()
    meta = {
        "generated_at": now(),
        "repos": len(repos),
        "plugins": len(plugins),
        "last_scan": dict(scan) if scan else None,
        "counts": {k: v for k, v in conn.execute("SELECT status, COUNT(*) FROM repo GROUP BY status").fetchall()},
        "native_level": {k: v for k, v in conn.execute("SELECT native_level, COUNT(*) FROM repo WHERE status='active' GROUP BY native_level").fetchall()},
    }
    (out_dir / "repos.json").write_text(json.dumps(repos, ensure_ascii=False), encoding="utf-8")
    (out_dir / "plugins.json").write_text(json.dumps(plugins, ensure_ascii=False), encoding="utf-8")
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return meta
