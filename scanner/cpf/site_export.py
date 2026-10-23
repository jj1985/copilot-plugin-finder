"""Export compact, columnar JSON for the static site (PLAN.md §6, §7).

Files written under site/public/data/:
  repos.json      columnar table of active repos (canonical and copies), dictionary-encoded
  plugins.json    columnar table of plugins at their home repo, with distributor counts
  detail/NNN.json detail shards (~300 repos each): manifests, plugins, markers, cluster members
  meta.json       scan summary, counts, coverage and marker census
"""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from .db import now

SHARD_SIZE = 200
DESC_MAX = 200
REPORT_URL = "https://github.com/jj1985/copilot-plugin-finder/issues/new"

REPO_COLUMNS = [
    "id", "name", "owner", "owner_type", "desc", "stars", "forks", "created", "committed", "pushed",
    "is_fork", "parent", "archived", "template", "language", "license",
    "kind", "level", "evidence", "format", "dual", "copspec", "exec",
    "mk_path", "pl_path", "mk_name", "plugins", "ext_plugins", "valid", "nwarn",
    "cluster", "canonical", "network", "copies", "diverged",
    "ref_mk", "ref_set", "seed", "topics", "shard", "head",
]
PLUGIN_COLUMNS = [
    "name", "version", "desc", "repo_id", "repo", "stars", "level", "format", "source_kind", "path",
    "exec", "category", "distributors", "seed", "canonical",
]


def _loads(s, default):
    if not s:
        return default
    try:
        return json.loads(s)
    except ValueError:
        return default


def _trunc(s: str | None, n: int = DESC_MAX) -> str | None:
    if not s:
        return None
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


class Dict_:
    def __init__(self):
        self.values: list = []
        self.index: dict = {}

    def code(self, v):
        if v is None or v == "":
            return -1
        if v not in self.index:
            self.index[v] = len(self.values)
            self.values.append(v)
        return self.index[v]


def export_site(conn: sqlite3.Connection, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "detail").mkdir(exist_ok=True)
    for old in (out_dir / "detail").glob("*.json"):
        old.unlink()

    topics = defaultdict(list)
    for r in conn.execute("SELECT repo_id, topic FROM repo_topic"):
        topics[r["repo_id"]].append(r["topic"])
    markers = defaultdict(list)
    for r in conn.execute("SELECT repo_id, marker_id, path, blob_oid FROM marker_hit"):
        markers[r["repo_id"]].append({"marker": r["marker_id"], "path": r["path"]})
    plugins_by_repo = defaultdict(list)
    for r in conn.execute("SELECT * FROM plugin ORDER BY repo_id, name"):
        plugins_by_repo[r["repo_id"]].append(dict(r))
    members_by_cluster = defaultdict(list)
    for r in conn.execute("SELECT id, full_name, stars, is_fork, is_canonical, diverged_fork, cluster_id FROM repo WHERE status='active' AND cluster_id IS NOT NULL ORDER BY is_canonical DESC, stars DESC"):
        members_by_cluster[r["cluster_id"]].append(dict(r))
    edges_by_repo = defaultdict(list)
    for r in conn.execute("SELECT e.repo_a, e.repo_b, e.signal, a.full_name an, b.full_name bn FROM edge e JOIN repo a ON a.id=e.repo_a JOIN repo b ON b.id=e.repo_b WHERE e.signal NOT IN ('plugin_tree')"):
        edges_by_repo[r["repo_a"]].append({"other": r["bn"], "signal": r["signal"]})
        edges_by_repo[r["repo_b"]].append({"other": r["an"], "signal": r["signal"]})
    adopters_by_ref = defaultdict(list)
    for r in conn.execute("SELECT a.marketplace_ref, r.full_name, r.stars FROM adopter a JOIN repo r ON r.id=a.repo_id ORDER BY r.stars DESC"):
        adopters_by_ref[r["marketplace_ref"].lower()].append({"repo": r["full_name"], "stars": r["stars"]})
    listed_in = defaultdict(list)
    for r in conn.execute("SELECT p.target_repo_id, p.target_path, p.entry_name, m.full_name, m.is_fork FROM plugin_ref p JOIN repo m ON m.id=p.marketplace_repo_id WHERE p.target_repo_id IS NOT NULL AND m.is_fork=0 AND m.is_canonical=1"):
        listed_in[(r["target_repo_id"], r["target_path"] or "")].append({"marketplace": r["full_name"], "entry": r["entry_name"]})

    # ---- repos ----
    d_owner, d_lang, d_lic = Dict_(), Dict_(), Dict_()
    rows = []
    detail: dict[int, dict] = {}
    repos = conn.execute(
        """SELECT * FROM repo WHERE status='active' ORDER BY is_canonical DESC, stars DESC, full_name"""
    ).fetchall()
    for i, r in enumerate(repos):
        rid = r["id"]
        shard = i // SHARD_SIZE
        warnings = _loads(r["schema_warnings"], [])
        rows.append([
            rid, r["full_name"], d_owner.code(r["owner"]), (r["owner_type"] or "")[:1],
            _trunc(r["description"]), r["stars"] or 0, r["forks"] or 0,
            (r["created_at"] or "")[:10], (r["committed_at"] or r["pushed_at"] or "")[:10], (r["pushed_at"] or "")[:10],
            int(r["is_fork"] or 0), r["parent_full_name"], int(r["is_archived"] or 0), int(r["is_template"] or 0),
            d_lang.code(r["language"]), d_lic.code(r["license"]),
            {"marketplace": "m", "plugin": "p", "both": "b"}.get(r["kind"], ""),
            0 if r["native_level"] == "copilot-authored" else 1,
            {"verified-root": 0, "verified-nested": 1}.get(r["evidence"], 2),
            r["format"], int(r["dual_format"] or 0), int(r["copilot_specific"] or 0), ",".join(_loads(r["executes_code"], [])),
            r["effective_marketplace_path"], r["effective_plugin_path"], r["marketplace_name"],
            r["plugin_count"] or 0, r["external_plugin_count"] or 0, r["schema_valid"], len(warnings),
            r["cluster_id"], int(r["is_canonical"] or 0), r["network_size"], r["indexed_copies"], int(r["diverged_fork"] or 0),
            r["referenced_by_marketplaces"] or 0, r["referenced_by_settings"] or 0, r["listed_by_seed"],
            topics.get(rid, [])[:12], shard, r["head_oid"],
        ])
        plist = []
        # copies (non-canonical members) point at the canonical repo for their plugin list
        for p in (plugins_by_repo.get(rid, []) if r["is_canonical"] else [])[:250]:
            plist.append({
                "name": p["name"], "version": p["version"], "desc": _trunc(p["description"], 300),
                "source_kind": p["source_kind"], "source_repo": p["source_repo"], "path": p["source_path"],
                "ref": p["ref"], "pinned": p["pinned"], "format": p["format"], "exec": _loads(p["executes_code"], []),
                "category": p["category"], "strict": p["strict"],
            })
        members = [m for m in members_by_cluster.get(r["cluster_id"], []) if m["id"] != rid][:60]
        detail[rid] = {
            "id": rid, "name": r["full_name"], "desc": r["description"], "homepage": r["homepage"],
            "readme": r["readme_excerpt"], "readme_name": r["readme_name"], "default_branch": r["default_branch"], "head": r["head_oid"],
            "marketplace": {"name": r["marketplace_name"], "owner": r["marketplace_owner_name"], "desc": r["marketplace_description"],
                            "version": r["marketplace_version"], "plugin_root": r["plugin_root"]} if r["marketplace_name"] else None,
            "plugin": {"name": r["plugin_name"], "version": r["plugin_version"], "desc": r["plugin_description"]} if r["plugin_name"] else None,
            "mk_path": r["effective_marketplace_path"], "pl_path": r["effective_plugin_path"],
            "shadowed": _loads(r["shadowed_manifests"], []), "warnings": warnings,
            "markers": markers.get(rid, []), "plugins": plist, "plugins_total": len(plugins_by_repo.get(rid, [])), "topics": topics.get(rid, []),
            "cluster": {"id": r["cluster_id"], "canonical": int(r["is_canonical"] or 0), "network": r["network_size"], "copies": r["indexed_copies"],
                        "members": [{"name": m["full_name"], "stars": m["stars"], "fork": m["is_fork"], "canonical": m["is_canonical"], "diverged": m["diverged_fork"]} for m in members],
                        "edges": edges_by_repo.get(rid, [])[:40]},
            "listed_in": listed_in.get((rid, ""), [])[:40],
            "adopters": adopters_by_ref.get(r["full_name"].lower(), [])[:40],
            "adopter_count": r["referenced_by_settings"] or 0,
            "seed": r["listed_by_seed"], "first_seen": r["first_seen"], "last_verified": r["last_verified"],
            "license": r["license"], "language": r["language"], "latest_release": r["latest_release"],
            "parent": r["parent_full_name"], "template": r["template_full_name"], "diverged": int(r["diverged_fork"] or 0),
            "surfaces": _loads(r["surfaces"], {}),
        }

    (out_dir / "repos.json").write_text(json.dumps({
        "generated_at": now(), "columns": REPO_COLUMNS, "rows": rows,
        "dicts": {"owner": d_owner.values, "language": d_lang.values, "license": d_lic.values},
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    for shard_no in range(0, (len(rows) + SHARD_SIZE - 1) // SHARD_SIZE):
        chunk = {str(rows[k][0]): detail[rows[k][0]] for k in range(shard_no * SHARD_SIZE, min(len(rows), (shard_no + 1) * SHARD_SIZE))}
        (out_dir / "detail" / f"{shard_no:03d}.json").write_text(json.dumps(chunk, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # ---- plugins (home repo only; marketplace listings of other repos become "distributors") ----
    prow = []
    repo_meta = {r[0]: r for r in rows}
    for r in conn.execute(
        """SELECT p.*, r.full_name, r.stars, r.native_level, r.listed_by_seed, r.is_canonical FROM plugin p JOIN repo r ON r.id=p.repo_id
           WHERE r.status='active' AND r.is_canonical=1 AND p.source_kind IN ('local','self') ORDER BY r.stars DESC, p.name"""):
        key = (r["repo_id"], (r["source_path"] or "").strip("./") if r["source_path"] not in (None, ".") else "")
        distributors = len({x["marketplace"] for x in listed_in.get(key, [])}) + len({x["marketplace"] for x in listed_in.get((r["repo_id"], ""), [])}) if key[1] else len({x["marketplace"] for x in listed_in.get((r["repo_id"], ""), [])})
        prow.append([
            r["name"], r["version"], _trunc(r["description"]), r["repo_id"], r["full_name"], r["stars"] or 0,
            0 if r["native_level"] == "copilot-authored" else 1, r["format"], r["source_kind"], r["source_path"],
            ",".join(_loads(r["executes_code"], [])), r["category"], distributors, r["listed_by_seed"], int(r["is_canonical"] or 0),
        ])
    (out_dir / "plugins.json").write_text(json.dumps({"columns": PLUGIN_COLUMNS, "rows": prow}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # ---- meta ----
    scan = conn.execute("SELECT * FROM scan WHERE kind IN ('scan','discover','verify','expand') ORDER BY id DESC LIMIT 1").fetchone()
    last_full = conn.execute("SELECT * FROM scan WHERE kind='scan' ORDER BY id DESC LIMIT 1").fetchone()
    golden = conn.execute("SELECT recall_golden FROM scan WHERE recall_golden IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
    meta = {
        "generated_at": now(),
        "report_url": REPORT_URL,
        "repos_active": len(rows),
        "repos_canonical": sum(1 for x in rows if x[REPO_COLUMNS.index("canonical")] == 1),
        "plugins": len(prow),
        "counts": {k: v for k, v in conn.execute("SELECT status, COUNT(*) FROM repo GROUP BY status").fetchall()},
        "by_level": {k: v for k, v in conn.execute("SELECT native_level, COUNT(*) FROM repo WHERE status='active' AND is_canonical=1 GROUP BY native_level").fetchall()},
        "clusters": conn.execute("SELECT COUNT(*) FROM cluster").fetchone()[0],
        "diverged_forks": conn.execute("SELECT COUNT(*) FROM repo WHERE diverged_fork=1").fetchone()[0],
        "adopters": conn.execute("SELECT COUNT(DISTINCT repo_id) FROM adopter").fetchone()[0],
        "golden_recall": golden["recall_golden"] if golden else None,
        "last_scan": {k: scan[k] for k in ("id", "kind", "started", "finished", "status")} if scan else None,
        "last_full_scan": {k: last_full[k] for k in ("id", "started", "finished", "status", "repos_seen", "repos_verified")} if last_full else None,
        "slices_incomplete": conn.execute("SELECT COUNT(*) FROM slice_run WHERE (incomplete_results=1) AND completed_at >= strftime('%Y-%m-%dT%H:%M:%SZ','now','-3 days')").fetchone()[0],
        "markers": [dict(r) for r in conn.execute("SELECT marker_id, COUNT(DISTINCT repo_id) repos FROM marker_hit GROUP BY marker_id ORDER BY repos DESC")],
        "requests": _loads(scan["requests_used"], None) if scan else None,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return meta
