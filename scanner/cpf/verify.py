"""Two-stage, head-oid gated verification over GraphQL (PLAN.md §3.4, §3.5).

V1: repository facts + root tree for ~50 repos per query. Repos whose head commit is
unchanged since the last verification stop here.
V2a: directory listings for the manifest directories that actually exist (~15 repos/query).
V2b: blob text for manifest oids not yet in the content-addressed `blob` table (~10 repos/query).
Then facets, plugins, adopters and status are computed and stored.
"""

from __future__ import annotations

import datetime as dt
import logging
import posixpath
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Iterable

from .db import j, now, upsert
from .gh import GitHub, GitHubError, GraphQLTimeout
from .manifest import (
    ALL_MANIFEST_PATHS,
    SETTINGS_PATHS,
    ManifestResult,
    compute_facets,
    enabled_plugins_from_settings,
    marketplace_ref,
    marketplaces_from_settings,
    parse_marketplace,
    parse_plugin,
    parse_settings,
    readme_excerpt,
)

log = logging.getLogger("cpf.verify")

REPO_FIELDS = """
  id databaseId nameWithOwner url description isFork
  parent { nameWithOwner databaseId }
  templateRepository { nameWithOwner databaseId }
  isArchived archivedAt isTemplate isMirror isEmpty isLocked
  stargazerCount forkCount createdAt pushedAt homepageUrl
  owner { __typename login ... on User { databaseId } ... on Organization { databaseId } }
  licenseInfo { spdxId } primaryLanguage { name }
  repositoryTopics(first: 20) { nodes { topic { name } } }
  latestRelease { tagName publishedAt }
  defaultBranchRef { name target { oid ... on Commit { committedDate tree { oid entries { name type oid } } } } }
"""
V1_QUERY = "query($ids:[ID!]!){ rateLimit{cost remaining} nodes(ids:$ids){ __typename ... on Repository {" + REPO_FIELDS + "} } }"

DIR_CANDIDATES = {
    ".github": [".github/plugin", ".github/copilot"],
    ".plugin": [".plugin"],
    ".claude-plugin": [".claude-plugin"],
    ".claude": [".claude"],
    ".vscode": [".vscode"],
    "plugins": ["plugins"],
    "com.github.copilot": ["com.github.copilot"],
}
README_NAMES = ("readme.md", "readme", "readme.rst", "readme.txt", "readme.markdown")
README_MAX_STORE = 20_000
BLOB_MAX_PARSE = 512_000
# A git symlink is a blob whose content is the link target path (mode 120000).
SYMLINK_TARGET_RE = re.compile(r"^[\w.@/-]{1,255}$")


@dataclass
class Batcher:
    """Adaptive batch size: halve on timeout and never grow back past a size that timed out."""
    size: int
    min_size: int = 3
    max_size: int = 60
    ceiling: int | None = None
    successes: int = 0

    def shrink(self) -> None:
        self.ceiling = max(self.min_size, self.size - 1)
        self.size = max(self.min_size, self.size // 2)
        self.successes = 0

    def grow(self) -> None:
        self.successes += 1
        if self.successes % 3:  # grow every third success, gently
            return
        cap = self.max_size if self.ceiling is None else min(self.max_size, self.ceiling)
        self.size = min(cap, self.size + max(1, self.size // 5))


@dataclass
class VSummary:
    v1_queries: int = 0
    v2a_queries: int = 0
    v2b_queries: int = 0
    repos_v1: int = 0
    repos_unchanged: int = 0
    repos_v2: int = 0
    repos_gone: int = 0
    repos_deferred: int = 0
    blobs_fetched: int = 0
    blobs_cached: int = 0
    timeouts: int = 0
    errors: list = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def _gql_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


class Verifier:
    def __init__(self, gh: GitHub, conn: sqlite3.Connection, scan_id: int, force: bool = False) -> None:
        self.gh = gh
        self.conn = conn
        self.scan_id = scan_id
        self.force = force
        self.v1 = Batcher(40, max_size=50)
        self.v2a = Batcher(15, max_size=30)
        self.v2b = Batcher(10, max_size=30)
        self.summary = VSummary()
        self._links: dict[tuple[int, str], tuple[str, str]] = {}  # (repo_id, link path) -> (target path, target blob oid)
        # lower-case full name -> subdirectories referenced as owner/repo:path (plugin lives there, not at root)
        self.extra_dirs: dict[str, set[str]] = {}

    def _extra_dirs_for(self, nd: dict) -> list[str]:
        dirs = self.extra_dirs.get(nd["nameWithOwner"].lower(), set())
        root = {e["name"] for e in self._root_entries(nd) if e.get("type") == "tree"}
        out: list[str] = []
        for d in sorted(dirs):
            d = d.strip("/")
            if d and d.split("/", 1)[0] in root:
                out.append(d)
                out.append(d + "/.claude-plugin")
        return out[:12]

    # ---------------- public ----------------

    def verify_pending(self, limit: int | None = None, statuses: Iterable[str] = ("candidate", "active", "demarked", "invalid", "unindexed", "no-manifest", "adopter")) -> VSummary:
        statuses = list(statuses)
        q = f"SELECT id, node_id FROM repo WHERE node_id IS NOT NULL AND status IN ({','.join('?' for _ in statuses)}) ORDER BY (status='candidate') DESC, last_verified ASC NULLS FIRST"
        rows = self.conn.execute(q, statuses).fetchall()
        if limit:
            rows = rows[:limit]
        ids = [r["node_id"] for r in rows]
        log.info("verifying %d repos", len(ids))
        self._run_ids(ids)
        return self.summary

    def verify_names(self, names: list[str]) -> dict[str, dict | None]:
        """Look up repos by owner/name (golden set, declared-only); returns {name: node|None} and processes them."""
        out: dict[str, dict | None] = {}
        step = 10  # REPO_FIELDS with the root tree is heavy; 10 per query stays under the GraphQL timeout
        for i in range(0, len(names), step):
            chunk = names[i:i + step]
            parts = []
            for k, full in enumerate(chunk):
                owner, _, name = full.partition("/")
                parts.append(f"r{k}: repository(owner:{_gql_str(owner)}, name:{_gql_str(name)}) {{ {REPO_FIELDS} }}")
            query = "query { rateLimit{cost remaining} " + " ".join(parts) + " }"
            try:
                data = self.gh.graphql(query)
            except GitHubError as exc:
                self.summary.errors.append(f"lookup: {exc}")
                for full in chunk:
                    out[full] = None
                continue
            nodes = []
            for k, full in enumerate(chunk):
                node = data.get(f"r{k}")
                out[full] = node
                if node:
                    nodes.append(node)
            self._after_v1(nodes, expected_ids=None)
        return out

    # ---------------- V1 ----------------

    def _run_ids(self, ids: list[str]) -> None:
        i = 0
        while i < len(ids):
            n = self.v1.size
            chunk = ids[i:i + n]
            try:
                data = self.gh.graphql(V1_QUERY, {"ids": chunk})
            except GraphQLTimeout as exc:
                self.summary.timeouts += 1
                if self.v1.size <= self.v1.min_size:
                    self.summary.errors.append(f"V1 timeout at min batch: {exc}")
                    i += n
                    continue
                self.v1.shrink()
                log.warning("V1 timeout; batch -> %d", self.v1.size)
                continue
            except GitHubError as exc:
                self.summary.errors.append(f"V1: {exc}")
                i += n
                continue
            self.summary.v1_queries += 1
            nodes = [nd for nd in (data.get("nodes") or []) if nd and nd.get("__typename") == "Repository"]
            self._after_v1(nodes, expected_ids=chunk)
            i += n
            self.v1.grow()

    def _after_v1(self, nodes: list[dict], expected_ids: list[str] | None) -> None:
        ts = now()
        # Compare by databaseId: REST search returns legacy node ids (MDEw...) for older repos while
        # GraphQL returns new-format ids (R_kgDO...), so node-id strings are not comparable.
        found_db = {nd["databaseId"] for nd in nodes}
        if expected_ids:
            rows = self.conn.execute(
                f"SELECT id, node_id FROM repo WHERE node_id IN ({','.join('?' for _ in expected_ids)})", expected_ids
            ).fetchall()
            for r in rows:
                if r["id"] not in found_db:
                    self._mark_gone(r["node_id"], ts)
        need_v2: list[dict] = []
        for nd in nodes:
            self.summary.repos_v1 += 1
            head = ((nd.get("defaultBranchRef") or {}).get("target") or {}).get("oid")
            st = self.conn.execute("SELECT head_oid, v2_done FROM repo_state WHERE repo_id=?", (nd["databaseId"],)).fetchone()
            self._store_cheap(nd, ts)
            if not self.force and st and st["v2_done"] and st["head_oid"] == head:
                self.summary.repos_unchanged += 1
                self.conn.execute("UPDATE repo SET last_verified=? WHERE id=?", (ts, nd["databaseId"]))
                continue
            if not head:  # empty repo
                self._finish_repo(nd, {}, {}, ts)
                continue
            need_v2.append(nd)
        self.conn.commit()
        if need_v2:
            self._run_v2(need_v2)

    def _mark_gone(self, node_id: str, ts: str) -> None:
        row = self.conn.execute("SELECT id, status FROM repo WHERE node_id=?", (node_id,)).fetchone()
        if not row:
            return
        if row["status"] != "gone":
            self.conn.execute("UPDATE repo SET status='gone', missing_since=COALESCE(missing_since, ?), last_verified=? WHERE id=?", (ts, ts, row["id"]))
            self.conn.execute("INSERT INTO scan_diff(scan_id, repo_id, change) VALUES (?,?,'gone')", (self.scan_id, row["id"]))
            self.summary.repos_gone += 1

    def _store_cheap(self, nd: dict, ts: str) -> None:
        """Repository facts available from V1 alone (also refreshes unchanged repos)."""
        rid = nd["databaseId"]
        owner = nd.get("owner") or {}
        dbr = nd.get("defaultBranchRef") or {}
        target = dbr.get("target") or {}
        prev = self.conn.execute("SELECT full_name, stars, forks, status FROM repo WHERE id=?", (rid,)).fetchone()
        rename = prev and prev["full_name"] and prev["full_name"].lower() != nd["nameWithOwner"].lower()
        topics = [t["topic"]["name"] for t in ((nd.get("repositoryTopics") or {}).get("nodes") or []) if t and t.get("topic")]
        row = {
            "id": rid,
            "node_id": nd["id"],
            "full_name": nd["nameWithOwner"],
            "owner": owner.get("login"),
            "owner_type": owner.get("__typename"),
            "owner_id": owner.get("databaseId"),
            "description": nd.get("description"),
            "homepage": nd.get("homepageUrl") or None,
            "stars": nd.get("stargazerCount"),
            "forks": nd.get("forkCount"),
            "created_at": nd.get("createdAt"),
            "pushed_at": nd.get("pushedAt"),
            "committed_at": target.get("committedDate"),
            "archived_at": nd.get("archivedAt"),
            "is_fork": int(bool(nd.get("isFork"))),
            "parent_full_name": (nd.get("parent") or {}).get("nameWithOwner"),
            "parent_id": (nd.get("parent") or {}).get("databaseId"),
            "template_full_name": (nd.get("templateRepository") or {}).get("nameWithOwner"),
            "template_id": (nd.get("templateRepository") or {}).get("databaseId"),
            "is_archived": int(bool(nd.get("isArchived"))),
            "is_template": int(bool(nd.get("isTemplate"))),
            "is_mirror": int(bool(nd.get("isMirror"))),
            "is_empty": int(bool(nd.get("isEmpty"))),
            "default_branch": dbr.get("name"),
            "license": (nd.get("licenseInfo") or {}).get("spdxId"),
            "language": (nd.get("primaryLanguage") or {}).get("name"),
            "latest_release": (nd.get("latestRelease") or {}).get("tagName"),
            "latest_release_at": (nd.get("latestRelease") or {}).get("publishedAt"),
            "head_oid": target.get("oid"),
            "root_tree_oid": ((target.get("tree") or {}).get("oid")),
            "last_verified": ts,
            "first_seen": ts,
        }
        upsert(self.conn, "repo", row, ["id"])
        # keep the original first_seen
        self.conn.execute("UPDATE repo SET first_seen=COALESCE((SELECT MIN(first_seen) FROM marker_hit WHERE repo_id=?), first_seen) WHERE id=?", (rid, rid))
        self.conn.execute("DELETE FROM repo_topic WHERE repo_id=?", (rid,))
        self.conn.executemany("INSERT OR IGNORE INTO repo_topic(repo_id, topic) VALUES (?,?)", [(rid, t) for t in topics])
        if rename:
            self.conn.execute("INSERT INTO scan_diff(scan_id, repo_id, change, detail) VALUES (?,?,'renamed',?)", (self.scan_id, rid, prev["full_name"]))
        if not prev or prev["stars"] != nd.get("stargazerCount") or prev["forks"] != nd.get("forkCount"):
            today = dt.date.today().isoformat()
            self.conn.execute("INSERT OR REPLACE INTO repo_snapshot(repo_id, date, stars, forks) VALUES (?,?,?,?)", (rid, today, nd.get("stargazerCount"), nd.get("forkCount")))

    # ---------------- V2 ----------------

    def _run_v2(self, nodes: list[dict]) -> None:
        # V2a: directory listings
        dir_entries: dict[int, dict[str, list[dict]]] = {nd["databaseId"]: {} for nd in nodes}
        failed: set[int] = set()  # repos whose V2a/V2b query failed: leave them as candidates for the next run
        wants: list[tuple[dict, list[str]]] = []
        for nd in nodes:
            root = {e["name"] for e in self._root_entries(nd)}
            dirs = [d for top, ds in DIR_CANDIDATES.items() if top in root for d in ds]
            dirs += [d for d in self._extra_dirs_for(nd) if d not in dirs]
            if dirs:
                wants.append((nd, dirs))
        i = 0
        while i < len(wants):
            chunk = wants[i:i + self.v2a.size]
            parts = []
            for k, (nd, dirs) in enumerate(chunk):
                head = nd["defaultBranchRef"]["target"]["oid"]
                objs = " ".join(
                    f"d{m}: object(expression:{_gql_str(head + ':' + d)}) {{ ... on Tree {{ entries {{ name type oid }} }} }}"
                    for m, d in enumerate(dirs)
                )
                parts.append(f"r{k}: node(id:{_gql_str(nd['id'])}) {{ ... on Repository {{ {objs} }} }}")
            query = "query { rateLimit{cost remaining} " + " ".join(parts) + " }"
            try:
                data = self.gh.graphql(query)
            except GraphQLTimeout:
                self.summary.timeouts += 1
                if self.v2a.size <= self.v2a.min_size:
                    self.summary.errors.append("V2a timeout at min batch")
                    failed.update(nd["databaseId"] for nd, _ in chunk)
                    i += len(chunk)
                    continue
                self.v2a.shrink()
                continue
            except GitHubError as exc:
                self.summary.errors.append(f"V2a: {exc}")
                failed.update(nd["databaseId"] for nd, _ in chunk)
                i += len(chunk)
                continue
            self.summary.v2a_queries += 1
            for k, (nd, dirs) in enumerate(chunk):
                r = data.get(f"r{k}") or {}
                for m, d in enumerate(dirs):
                    obj = r.get(f"d{m}")
                    if obj and obj.get("entries") is not None:
                        dir_entries[nd["databaseId"]][d] = obj["entries"]
            i += len(chunk)
            self.v2a.grow()

        # V2b: blobs
        plans: list[tuple[dict, list[tuple[str, str]]]] = []  # (node, [(path, oid)])
        for nd in nodes:
            paths = self._manifest_paths(nd, dir_entries[nd["databaseId"]])
            missing = [(p, oid) for p, oid in paths if not self._blob_cached(oid)]
            self.summary.blobs_cached += len(paths) - len(missing)
            plans.append((nd, missing))
        i = 0
        while i < len(plans):
            chunk = [pl for pl in plans[i:i + self.v2b.size]]
            active = [(nd, m) for nd, m in chunk if m]
            if active:
                parts = []
                for k, (nd, missing) in enumerate(active):
                    head = nd["defaultBranchRef"]["target"]["oid"]
                    objs = " ".join(
                        f"b{m}: object(expression:{_gql_str(head + ':' + p)}) {{ ... on Blob {{ oid byteSize isBinary text }} }}"
                        for m, (p, _) in enumerate(missing)
                    )
                    parts.append(f"r{k}: node(id:{_gql_str(nd['id'])}) {{ ... on Repository {{ {objs} }} }}")
                query = "query { rateLimit{cost remaining} " + " ".join(parts) + " }"
                try:
                    data = self.gh.graphql(query)
                except GraphQLTimeout:
                    self.summary.timeouts += 1
                    if self.v2b.size <= self.v2b.min_size:
                        self.summary.errors.append("V2b timeout at min batch")
                        failed.update(nd["databaseId"] for nd, _ in active)
                        i += len(chunk)
                        continue
                    self.v2b.shrink()
                    continue
                except GitHubError as exc:
                    self.summary.errors.append(f"V2b: {exc}")
                    failed.update(nd["databaseId"] for nd, _ in active)
                    i += len(chunk)
                    continue
                self.summary.v2b_queries += 1
                ts = now()
                for k, (nd, missing) in enumerate(active):
                    r = data.get(f"r{k}") or {}
                    for m, (p, oid) in enumerate(missing):
                        blob = r.get(f"b{m}")
                        if blob and blob.get("oid"):
                            self._store_blob(blob, p, ts)
                            self.summary.blobs_fetched += 1
                self.v2b.grow()
            self._resolve_symlinks([nd for nd, _ in chunk if nd["databaseId"] not in failed], dir_entries)
            ts = now()
            for nd, _ in chunk:
                rid = nd["databaseId"]
                if rid in failed:
                    self.summary.repos_deferred += 1
                    continue
                paths = dict(self._manifest_paths(nd, dir_entries[rid]))
                # a blob we needed is still missing (query partially failed): defer rather than mis-classify
                if any(not self._blob_cached(oid) for _, oid in paths.items()):
                    self.summary.repos_deferred += 1
                    continue
                self._finish_repo(nd, dir_entries[rid], paths, ts)
            self.conn.commit()
            i += len(chunk)

    def _resolve_symlinks(self, nodes: list[dict], dir_entries: dict[int, dict[str, list[dict]]]) -> None:
        """Manifest paths that are git symlinks: fetch the target blob so the manifest can be parsed."""
        fetch: list[tuple[dict, str, str]] = []
        for nd in nodes:
            rid = nd["databaseId"]
            for p, oid in self._manifest_paths(nd, dir_entries.get(rid, {})):
                if not (p.endswith(("plugin.json", "marketplace.json")) or p in SETTINGS_PATHS):
                    continue
                text = self._blob_text(oid)
                if not text:
                    continue
                t = text.strip()
                if "\n" in t or "{" in t or not SYMLINK_TARGET_RE.match(t):
                    continue
                target = posixpath.normpath(posixpath.join(posixpath.dirname(p), t))
                if target.startswith("..") or target == p:
                    continue
                cached = self.conn.execute("SELECT oid FROM blob b JOIN manifest_history h ON h.blob_oid=b.oid WHERE h.repo_id=? AND h.path=?", (rid, target)).fetchone()
                fetch.append((nd, p, target))
        for i in range(0, len(fetch), 20):
            chunk = fetch[i:i + 20]
            parts = []
            for k, (nd, p, target) in enumerate(chunk):
                head = nd["defaultBranchRef"]["target"]["oid"]
                parts.append(f"l{k}: node(id:{_gql_str(nd['id'])}) {{ ... on Repository {{ o: object(expression:{_gql_str(head + ':' + target)}) {{ ... on Blob {{ oid byteSize isBinary text }} }} }} }}")
            query = "query { rateLimit{cost remaining} " + " ".join(parts) + " }"
            try:
                data = self.gh.graphql(query)
            except GitHubError as exc:
                self.summary.errors.append(f"symlink fetch: {exc}")
                continue
            ts = now()
            for k, (nd, p, target) in enumerate(chunk):
                blob = (data.get(f"l{k}") or {}).get("o")
                if blob and blob.get("oid"):
                    self._store_blob(blob, target, ts)
                    self._links[(nd["databaseId"], p)] = (target, blob["oid"])
                    self.summary.blobs_fetched += 1

    # ---------------- offline re-classification ----------------

    def reclassify(self, limit: int | None = None) -> int:
        """Recompute facets/status from cached blobs and stored listings (no network). Returns repos processed."""
        import json as _json
        rows = self.conn.execute(
            """SELECT r.id, r.node_id, r.full_name, s.head_oid, s.root_tree_oid, s.root_entries, s.dir_entries, s.paths
               FROM repo r JOIN repo_state s ON s.repo_id=r.id WHERE s.root_entries IS NOT NULL AND s.paths IS NOT NULL"""
        ).fetchall()
        if limit:
            rows = rows[:limit]
        ts = now()
        n = 0
        for r in rows:
            nd = {"databaseId": r["id"], "id": r["node_id"], "nameWithOwner": r["full_name"],
                  "defaultBranchRef": {"target": {"oid": r["head_oid"], "tree": {"oid": r["root_tree_oid"], "entries": _json.loads(r["root_entries"])}}}}
            dirs = _json.loads(r["dir_entries"] or "{}")
            paths = _json.loads(r["paths"])
            self._resolve_symlinks([nd], {r["id"]: dirs})
            self._finish_repo(nd, dirs, paths, ts)
            n += 1
            if n % 500 == 0:
                self.conn.commit()
        self.conn.commit()
        return n

    # ---------------- helpers ----------------

    @staticmethod
    def _root_entries(nd: dict) -> list[dict]:
        return (((nd.get("defaultBranchRef") or {}).get("target") or {}).get("tree") or {}).get("entries") or []

    def _manifest_paths(self, nd: dict, dirs: dict[str, list[dict]]) -> list[tuple[str, str]]:
        """(path, oid) for every manifest/settings/README file present at HEAD."""
        out: list[tuple[str, str]] = []
        root = {e["name"]: e for e in self._root_entries(nd) if e.get("type") == "blob"}
        for name in ("marketplace.json", "plugin.json"):
            if name in root:
                out.append((name, root[name]["oid"]))
        extra = set(self._extra_dirs_for(nd))
        for d, entries in dirs.items():
            for e in entries:
                if e.get("type") != "blob":
                    continue
                p = f"{d}/{e['name']}"
                if p in ALL_MANIFEST_PATHS or p in SETTINGS_PATHS or (d in extra and e["name"] == "plugin.json"):
                    out.append((p, e["oid"]))
        # README: only when the repo has a Copilot-authored manifest path (keeps Claude-format cheap)
        copilot_paths = {p for p, _ in out if p.startswith((".github/plugin/", ".plugin/")) or p in ("marketplace.json", "plugin.json")}
        if copilot_paths:
            for name, e in root.items():
                if name.lower() in README_NAMES:
                    out.append((name, e["oid"]))
                    break
        return out

    def _blob_cached(self, oid: str) -> bool:
        return self.conn.execute("SELECT 1 FROM blob WHERE oid=?", (oid,)).fetchone() is not None

    def _store_blob(self, blob: dict, path: str, ts: str) -> None:
        text = None if blob.get("isBinary") else blob.get("text")
        parsed = None
        perr = None
        if text is not None and path.lower().endswith(".json") and (blob.get("byteSize") or 0) <= BLOB_MAX_PARSE:
            try:
                import json as _json
                parsed = _json.dumps(_json.loads(text), ensure_ascii=False, sort_keys=True)
            except ValueError as exc:
                perr = str(exc)[:200]
        if text is not None and not path.lower().endswith(".json"):
            text = text[:README_MAX_STORE]
        self.conn.execute(
            "INSERT OR IGNORE INTO blob(oid, byte_size, text, parsed_json, parse_error, first_seen) VALUES (?,?,?,?,?,?)",
            (blob["oid"], blob.get("byteSize"), text, parsed, perr, ts),
        )

    def _blob_text(self, oid: str) -> str | None:
        row = self.conn.execute("SELECT text FROM blob WHERE oid=?", (oid,)).fetchone()
        return row["text"] if row else None

    def _finish_repo(self, nd: dict, dirs: dict[str, list[dict]], paths: dict[str, str], ts: str) -> None:
        rid = nd["databaseId"]
        root_entries = {e["name"] for e in self._root_entries(nd)}
        manifests: dict[str, ManifestResult] = {}
        for p, oid in paths.items():
            link = self._links.get((rid, p))
            text = self._blob_text(link[1] if link else oid)
            if p.endswith("marketplace.json"):
                manifests[p] = parse_marketplace(p, text)
            elif p.endswith("plugin.json"):
                manifests[p] = parse_plugin(p, text, root_entries)
            else:
                continue
            if link:
                manifests[p].warnings.append(f"symlink to {link[0]} (resolved; may break on Windows checkouts)")
        f = compute_facets(root_entries, manifests)

        # adopters (settings files)
        self.conn.execute("DELETE FROM adopter WHERE repo_id=?", (rid,))
        n_adopter = 0
        for sp in SETTINGS_PATHS:
            if sp in paths:
                sr = parse_settings(sp, self._blob_text(paths[sp]))
                if sr.ok and sr.data:
                    enabled = enabled_plugins_from_settings(sr.data)
                    for m in marketplaces_from_settings(sr.data):
                        ref = marketplace_ref(m)
                        if ref:
                            self.conn.execute(
                                "INSERT OR REPLACE INTO adopter(repo_id, marketplace_ref, file_path, enabled_plugins) VALUES (?,?,?,?)",
                                (rid, ref, sp, j(enabled)),
                            )
                            n_adopter += 1

        # plugins from marketplace entries first
        self.conn.execute("DELETE FROM plugin WHERE repo_id=?", (rid,))
        self.conn.execute("DELETE FROM plugin_ref WHERE marketplace_repo_id=?", (rid,))
        plugin_dirs = {e["name"]: e["oid"] for e in dirs.get("plugins", []) if e.get("type") == "tree"}
        n_ext = 0
        entries = (f.marketplace or {}).get("plugins") or []
        for p in entries:
            src = p["source"]
            tree_oid = None
            if src["kind"] == "local" and src.get("path", "").startswith("plugins/"):
                tree_oid = plugin_dirs.get(src["path"].split("/", 2)[1])
            if src["kind"] != "local":
                n_ext += 1
            self.conn.execute(
                """INSERT OR REPLACE INTO plugin(repo_id, name, version, description, source_kind, source_host, source_repo, source_path, ref, sha, pinned,
                   keywords, category, tags, strict, format, dir_tree_oid, executes_code)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (rid, p["name"], p.get("version"), p.get("description"), src["kind"], src.get("host"), src.get("repo"), src.get("path"),
                 src.get("ref"), src.get("sha"), src.get("pinned", 0), j(p.get("keywords")), p.get("category"), j(p.get("tags")),
                 p.get("strict"), f.format, tree_oid, j(p.get("executes_code"))),
            )
            if src["kind"] == "github" and src.get("repo"):
                self.conn.execute(
                    "INSERT OR REPLACE INTO plugin_ref(marketplace_repo_id, entry_name, target_repo, target_path, ref, sha) VALUES (?,?,?,?,?,?)",
                    (rid, p["name"], src["repo"], src.get("path"), src.get("ref"), src.get("sha")),
                )
        if f.plugin and not entries:
            pdir = posixpath.dirname(f.effective_plugin_path or "") or "."
            if pdir.endswith((".github/plugin", ".plugin", ".claude-plugin")):
                pdir = "."
            self.conn.execute(
                "INSERT OR REPLACE INTO plugin(repo_id, name, version, description, source_kind, source_path, keywords, category, tags, format, executes_code) VALUES (?,?,?,?, 'self', ?, ?,?,?,?,?)",
                (rid, f.plugin["name"], f.plugin.get("version"), f.plugin.get("description"), pdir, j(f.plugin.get("keywords")), f.plugin.get("category"), j(f.plugin.get("tags")), f.plugin.get("format"), j(f.executes_code)),
            )

        # manifest history
        for p, oid in paths.items():
            if p.endswith(("plugin.json", "marketplace.json")):
                self.conn.execute(
                    "INSERT INTO manifest_history(repo_id, path, blob_oid, first_seen, last_seen) VALUES (?,?,?,?,?) ON CONFLICT(repo_id, path, blob_oid) DO UPDATE SET last_seen=excluded.last_seen",
                    (rid, p, oid, ts, ts),
                )

        prev = self.conn.execute("SELECT status, evidence FROM repo WHERE id=?", (rid,)).fetchone()
        has_manifest_file = any(p.endswith(("plugin.json", "marketplace.json")) for p in paths)
        referred = self.conn.execute("SELECT 1 FROM referral WHERE full_name_lc=?", (nd["nameWithOwner"].lower(),)).fetchone() is not None
        if f.kind:
            status = "active"
        elif has_manifest_file:
            status = "invalid"
        elif n_adopter:
            status = "adopter"          # consumer-side settings only: not a plugin, but it names marketplaces
        elif referred:
            status = "declared"         # named by a marketplace or settings file, but no manifest found
        elif prev and prev["status"] in ("active", "invalid"):
            status = "demarked"         # had a manifest before, none at HEAD now
        else:
            status = "no-manifest"      # search hit but nothing usable at HEAD (removed since indexing)
        readme = None
        rname = next((p for p in paths if p.lower() in README_NAMES), None)
        if rname:
            readme = readme_excerpt(self._blob_text(paths[rname]))
        mk = f.marketplace or {}
        pl = f.plugin or {}
        self.conn.execute(
            """UPDATE repo SET kind=?, native_level=?, evidence=?, format=?, dual_format=?, copilot_specific=?, executes_code=?, surfaces=?,
               effective_marketplace_path=?, effective_plugin_path=?, shadowed_manifests=?,
               marketplace_name=?, marketplace_owner_name=?, marketplace_description=?, marketplace_version=?, plugin_root=?,
               plugin_name=?, plugin_version=?, plugin_description=?,
               plugin_count=?, external_plugin_count=?, schema_valid=?, schema_warnings=?,
               readme_name=?, readme_oid=?, readme_excerpt=?, status=?, last_verified=?, missing_since=NULL, marker_version=2
               WHERE id=?""",
            (f.kind, f.native_level, f.evidence, f.format, f.dual_format, f.copilot_specific, j(f.executes_code),
             j({"cli": "docs", "vscode": "unknown", "app": "unknown", "cloud_agent": "unknown"}),
             f.effective_marketplace_path, f.effective_plugin_path, j(f.shadowed),
             mk.get("name"), mk.get("owner_name"), mk.get("description"), mk.get("version"), mk.get("plugin_root"),
             pl.get("name"), pl.get("version"), pl.get("description"),
             len(entries) if entries else (1 if f.plugin else 0), n_ext, f.schema_valid, j(f.warnings),
             rname, paths.get(rname) if rname else None, readme, status, ts, rid),
        )
        head = ((nd.get("defaultBranchRef") or {}).get("target") or {}).get("oid")
        tree = (((nd.get("defaultBranchRef") or {}).get("target") or {}).get("tree") or {}).get("oid")
        self.conn.execute(
            "INSERT OR REPLACE INTO repo_state(repo_id, head_oid, root_tree_oid, verified_at, v2_done, root_entries, dir_entries, paths) VALUES (?,?,?,?,1,?,?,?)",
            (rid, head, tree, ts,
             j([{"name": e["name"], "type": e.get("type"), "oid": e.get("oid")} for e in self._root_entries(nd)]),
             j({d: [{"name": e["name"], "type": e.get("type"), "oid": e.get("oid")} for e in es] for d, es in dirs.items()}),
             j(paths)),
        )
        change = "new" if not prev or prev["status"] == "candidate" else ("changed" if prev["status"] == status else None)
        if prev and prev["status"] != status and prev["status"] != "candidate":
            change = f"{prev['status']}->{status}"
        if change:
            self.conn.execute("INSERT INTO scan_diff(scan_id, repo_id, change) VALUES (?,?,?)", (self.scan_id, rid, change))
        self.summary.repos_v2 += 1
