"""De-duplication (PLAN.md §5, v2 rules).

Edges:
  definitive  fork (unless diverged), tree (identical non-trivial root tree)
  strong      manifest (same effective manifest blob), readme (same README blob), plugin_tree (shared plugin dir oid)
  family      template (generated from the same template repo; recorded, never unioned)
Union-find runs on definitive edges; a pair joins on strong evidence only when two independent
strong signals agree. Everything else stays a `similar_to` edge in the `edge` table.
Boilerplate guard: a blob shared by more than BOILERPLATE_OWNERS distinct non-fork owners, or
smaller than BOILERPLATE_MIN_BYTES, gives no evidence.
"""

from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations

from .db import j, now

log = logging.getLogger("cpf.dedup")

BOILERPLATE_OWNERS = 5
BOILERPLATE_MIN_BYTES = 300
DIVERGED_MIN_STARS = 5
MAX_GROUP = 400  # pairs within a shared-oid group are capped by linking to the first member


@dataclass
class DSummary:
    repos: int = 0
    edges: dict = field(default_factory=dict)
    clusters: int = 0
    multi_member_clusters: int = 0
    largest_cluster: int = 0
    diverged_forks: int = 0
    template_blobs: int = 0

    def as_dict(self) -> dict:
        return dict(self.__dict__)


class UF:
    def __init__(self):
        self.p: dict[int, int] = {}

    def find(self, x: int) -> int:
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def run_dedup(conn: sqlite3.Connection, scan_id: int) -> DSummary:
    s = DSummary()
    ts = now()
    repos = {r["id"]: dict(r) for r in conn.execute(
        """SELECT id, full_name, owner, owner_type, is_fork, parent_id, parent_full_name, template_id, root_tree_oid, head_oid,
                  stars, forks, created_at, committed_at, is_archived, status, evidence, marketplace_name, readme_oid,
                  listed_by_seed, effective_marketplace_path, effective_plugin_path, kind
           FROM repo WHERE status='active'""")}
    s.repos = len(repos)
    ids = set(repos)
    conn.execute("UPDATE repo SET diverged_fork=0 WHERE status!='active'")

    # effective manifest blob per repo (latest manifest_history row for the effective path)
    man_oid: dict[int, str] = {}
    for r in conn.execute(
        """SELECT h.repo_id, h.path, h.blob_oid FROM manifest_history h JOIN repo r ON r.id=h.repo_id
           WHERE r.status='active' AND (h.path=r.effective_marketplace_path OR (r.effective_marketplace_path IS NULL AND h.path=r.effective_plugin_path))
           ORDER BY h.last_seen"""):
        man_oid[r["repo_id"]] = r["blob_oid"]
    blob_size = {r["oid"]: r["byte_size"] or 0 for r in conn.execute("SELECT oid, byte_size FROM blob")}

    edges: list[tuple[int, int, str, dict]] = []
    counts: dict[str, int] = defaultdict(int)

    def add(a: int, b: int, sig: str, ev: dict | None = None) -> None:
        if a == b or a not in ids or b not in ids:
            return
        a, b = (a, b) if a < b else (b, a)
        edges.append((a, b, sig, ev or {}))
        counts[sig] += 1

    # ---- fork edges with divergence test ----
    uf = UF()
    diverged_pairs: set[tuple[int, int]] = set()
    for rid, r in repos.items():
        pid = r["parent_id"]
        if not r["is_fork"] or not pid or pid not in repos:
            continue
        p = repos[pid]
        same_manifest = man_oid.get(rid) is not None and man_oid.get(rid) == man_oid.get(pid)
        same_head = r["head_oid"] and r["head_oid"] == p["head_oid"]
        diverged = False
        if not (same_manifest or same_head):
            diverged = (
                (r["stars"] or 0) >= DIVERGED_MIN_STARS
                or (r["marketplace_name"] and p["marketplace_name"] and r["marketplace_name"] != p["marketplace_name"])
                or bool(r["listed_by_seed"])
                or bool(p["is_archived"])
            )
        add(rid, pid, "fork", {"diverged": diverged, "same_manifest": same_manifest, "same_head": bool(same_head)})
        if diverged:
            s.diverged_forks += 1
            diverged_pairs.add((min(rid, pid), max(rid, pid)))
            conn.execute("UPDATE repo SET diverged_fork=1 WHERE id=?", (rid,))
        else:
            conn.execute("UPDATE repo SET diverged_fork=0 WHERE id=?", (rid,))
            uf.union(pid, rid)

    # ---- template family (recorded only) ----
    for rid, r in repos.items():
        if r["template_id"] and r["template_id"] in repos:
            add(rid, r["template_id"], "template")

    # ---- identical root tree (definitive, guarded) ----
    by_tree: dict[str, list[int]] = defaultdict(list)
    for rid, r in repos.items():
        if r["root_tree_oid"] and r["kind"]:
            by_tree[r["root_tree_oid"]].append(rid)
    for oid, members in by_tree.items():
        if len(members) < 2:
            continue
        members = sorted(members)[:MAX_GROUP]
        for other in members[1:]:
            pair = (members[0], other)
            add(*pair, "tree")
            if pair not in diverged_pairs:  # identical tree with a diverged fork cannot happen (manifest differs), but be safe
                uf.union(members[0], other)

    # ---- strong signals: manifest blob, readme blob, plugin dir tree ----
    strong_pairs: dict[tuple[int, int], set[str]] = defaultdict(set)

    def group_strong(groups: dict[str, list[int]], sig: str, size_of) -> None:
        for oid, members in groups.items():
            members = sorted(set(members))
            if len(members) < 2:
                continue
            if size_of(oid) < BOILERPLATE_MIN_BYTES:
                mark_template(oid, members, "small blob")
                continue
            nonfork_owners = {repos[m]["owner"] for m in members if not repos[m]["is_fork"]}
            if len(nonfork_owners) > BOILERPLATE_OWNERS:
                mark_template(oid, members, f"{len(nonfork_owners)} non-fork owners")
                continue
            members = members[:MAX_GROUP]
            for a, b in combinations(members, 2):
                if uf.find(a) == uf.find(b):
                    continue  # already definitive
                strong_pairs[(a, b)].add(sig)
                add(a, b, sig)

    def mark_template(oid: str, members: list[int], reason: str) -> None:
        s.template_blobs += 1
        conn.execute("INSERT OR REPLACE INTO template_blob(oid, owner_count, reason) VALUES (?,?,?)",
                     (oid, len({repos[m]["owner"] for m in members}), reason))
        conn.execute("UPDATE blob SET is_template_blob=1, owner_count=? WHERE oid=?", (len({repos[m]["owner"] for m in members}), oid))

    by_manifest: dict[str, list[int]] = defaultdict(list)
    for rid, oid in man_oid.items():
        if rid in repos:
            by_manifest[oid].append(rid)
    group_strong(by_manifest, "manifest", lambda o: blob_size.get(o, 0))

    by_readme: dict[str, list[int]] = defaultdict(list)
    for rid, r in repos.items():
        if r["readme_oid"]:
            by_readme[r["readme_oid"]].append(rid)
    group_strong(by_readme, "readme", lambda o: blob_size.get(o, 0))

    by_ptree: dict[str, list[int]] = defaultdict(list)
    for r in conn.execute("SELECT repo_id, dir_tree_oid FROM plugin WHERE dir_tree_oid IS NOT NULL"):
        if r["repo_id"] in repos:
            by_ptree[r["dir_tree_oid"]].append(r["repo_id"])
    # a shared plugin directory is strong at plugin level; at repo level it counts as one strong signal
    group_strong(by_ptree, "plugin_tree", lambda o: BOILERPLATE_MIN_BYTES)

    # two independent strong signals -> union, except across a fork edge judged diverged
    # (a maintained hard fork keeps the upstream README and most plugin directories; that is not identity).
    # The root of a diverged fork is also kept apart from the parent's cluster transitively.
    diverged_roots = {rid for (a, b) in diverged_pairs for rid in (a, b) if repos[rid]["is_fork"] and repos[rid]["parent_id"] in (a, b)}
    for (a, b), sigs in strong_pairs.items():
        if len(sigs) >= 2:
            if (a, b) in diverged_pairs or uf.find(a) in diverged_roots or uf.find(b) in diverged_roots:
                add(a, b, "strong2_blocked", {"signals": sorted(sigs), "reason": "diverged fork"})
                continue
            uf.union(a, b)
            add(a, b, "strong2", {"signals": sorted(sigs)})

    # ---- persist edges ----
    conn.execute("DELETE FROM edge")
    conn.executemany(
        "INSERT OR REPLACE INTO edge(repo_a, repo_b, signal, evidence, created_at) VALUES (?,?,?,?,?)",
        [(a, b, sig, j(ev), ts) for a, b, sig, ev in edges],
    )
    s.edges = dict(conn.execute("SELECT signal, COUNT(*) FROM edge GROUP BY signal").fetchall())

    # ---- manual overrides ----
    for ov in conn.execute("SELECT action, repo_ids FROM cluster_override"):
        import json as _json
        try:
            rids = [int(x) for x in _json.loads(ov["repo_ids"])]
        except (ValueError, TypeError):
            continue
        if ov["action"] == "merge":
            for x in rids[1:]:
                uf.union(rids[0], x)
        # 'split' is handled by excluding definitive unions in a future pass; recorded for now

    # ---- clusters and canonical ----
    members: dict[int, list[int]] = defaultdict(list)
    for rid in repos:
        members[uf.find(rid)].append(rid)

    rank_seed = {"github/awesome-copilot": 0, "github/copilot-plugins": 1}

    def key(rid: int):
        r = repos[rid]
        return (
            0 if (not r["is_archived"] and r["evidence"] == "verified-root") else 1,
            0 if not r["is_fork"] else 1,
            0 if r["listed_by_seed"] else 1,
            r["created_at"] or "9999",
            -(r["stars"] or 0),
            0 if r["owner_type"] == "Organization" else 1,
            r["full_name"].lower(),
        )

    conn.execute("DELETE FROM cluster")
    conn.execute("UPDATE repo SET cluster_id=NULL, is_canonical=1, network_size=NULL, indexed_copies=NULL WHERE status!='active'")
    cid = 0
    for root, mem in members.items():
        cid += 1
        canon = min(mem, key=key)
        fork_members = sum(1 for m in mem if repos[m]["is_fork"] and m != canon)
        clone_members = sum(1 for m in mem if not repos[m]["is_fork"] and m != canon)
        network = max(repos[canon]["forks"] or 0, fork_members)
        conn.execute("INSERT INTO cluster(id, canonical_repo_id, size, fork_members, clone_members, computed_at) VALUES (?,?,?,?,?,?)",
                     (cid, canon, len(mem), fork_members, clone_members, ts))
        for m in mem:
            conn.execute("UPDATE repo SET cluster_id=?, is_canonical=?, network_size=?, indexed_copies=? WHERE id=?",
                         (cid, int(m == canon), network if m == canon else None, clone_members if m == canon else None, m))
        if len(mem) > 1:
            s.multi_member_clusters += 1
        s.largest_cluster = max(s.largest_cluster, len(mem))
    s.clusters = cid
    conn.commit()
    return s


def audit_report(conn: sqlite3.Connection, out_path, sample: int = 25) -> None:
    """Write a Markdown sample of clusters for manual review."""
    lines = ["# De-dup audit sample", "", f"Generated {now()}.", ""]
    sizes = conn.execute("SELECT size, COUNT(*) FROM cluster GROUP BY size ORDER BY size").fetchall()
    lines += ["## Cluster size distribution", "", "| size | clusters |", "|---|---|"]
    lines += [f"| {a} | {b} |" for a, b in sizes]
    lines += ["", "## Largest clusters", ""]
    for c in conn.execute("SELECT c.id, c.size, c.fork_members, c.clone_members, r.full_name, r.stars FROM cluster c JOIN repo r ON r.id=c.canonical_repo_id ORDER BY c.size DESC LIMIT ?", (sample,)):
        lines.append(f"- cluster {c['id']}: canonical `{c['full_name']}` ({c['stars']}★), size {c['size']}, forks {c['fork_members']}, clones {c['clone_members']}")
        for m in conn.execute("SELECT full_name, is_fork, stars FROM repo WHERE cluster_id=? AND is_canonical=0 ORDER BY stars DESC LIMIT 5", (c["id"],)):
            lines.append(f"    - {m['full_name']} ({'fork' if m['is_fork'] else 'clone'}, {m['stars']}★)")
    lines += ["", "## Non-fork clone pairs (strong evidence) for spot-checking", ""]
    for e in conn.execute(
        """SELECT a.full_name an, b.full_name bn, e.signal, e.evidence FROM edge e JOIN repo a ON a.id=e.repo_a JOIN repo b ON b.id=e.repo_b
           WHERE e.signal IN ('tree','strong2') AND a.is_fork=0 AND b.is_fork=0 ORDER BY RANDOM() LIMIT ?""", (sample,)):
        lines.append(f"- `{e['an']}` ~ `{e['bn']}` via {e['signal']} {e['evidence'] or ''}")
    merged_back = conn.execute("SELECT COUNT(*) FROM repo f JOIN repo p ON p.id=f.parent_id WHERE f.diverged_fork=1 AND f.cluster_id=p.cluster_id").fetchone()[0]
    lines += ["", f"## Diverged forks (own record kept; {merged_back} still share the parent's cluster)", ""]
    for r in conn.execute("SELECT full_name, parent_full_name, stars, marketplace_name FROM repo WHERE diverged_fork=1 ORDER BY stars DESC LIMIT ?", (sample,)):
        lines.append(f"- `{r['full_name']}` fork of `{r['parent_full_name']}` ({r['stars']}★, marketplace `{r['marketplace_name']}`)")
    lines += ["", "## Similar-to only (single strong signal, not merged)", ""]
    for e in conn.execute(
        """SELECT a.full_name an, b.full_name bn, e.signal FROM edge e JOIN repo a ON a.id=e.repo_a JOIN repo b ON b.id=e.repo_b
           WHERE e.signal IN ('manifest','readme','plugin_tree') AND a.cluster_id!=b.cluster_id ORDER BY RANDOM() LIMIT ?""", (sample,)):
        lines.append(f"- `{e['an']}` ~ `{e['bn']}` ({e['signal']})")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
