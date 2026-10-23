"""Discovery: partitioned, resumable GitHub code-search sweeps per marker family.

Rules (PLAN.md §3.2): a slice is complete only when its last page was short and
`incomplete_results` was false. Slices over the cap are split on `size:`, then on
content terms (`q term` / `q NOT term`), then on owner carve-outs (`user:X` / `-user:X`).
Every hit must match the family's exact path regex before it becomes a marker_hit.
"""

from __future__ import annotations

import logging
import math
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .db import now
from .gh import GitHub, GitHubError
from .markers import Family, Rules

log = logging.getLogger("cpf.discover")

PER_PAGE = 100
MAX_PAGES = 10
MAX_DEPTH = 60


class BudgetExhausted(Exception):
    pass


@dataclass
class Summary:
    slices: int = 0
    slices_incomplete: int = 0
    slices_over_cap: int = 0
    pages: int = 0
    items: int = 0
    accepted: int = 0
    rejected_path: int = 0
    repos: set = field(default_factory=set)
    budget_exhausted: bool = False
    errors: list = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items() if k != "repos"}
        d["repos"] = len(self.repos)
        return d


@dataclass
class Slice:
    base: str
    extra: tuple[str, ...] = ()
    size: tuple[int, int] | None = None

    @property
    def query(self) -> str:
        q = self.base
        if self.extra:
            q += " " + " ".join(self.extra)
        if self.size:
            lo, hi = self.size
            q += f" size:{lo}..{hi}"
        return q


class Discoverer:
    def __init__(self, gh: GitHub, conn: sqlite3.Connection, rules: Rules, scan_id: int,
                 max_requests: int | None = None, resume_hours: int = 20) -> None:
        self.gh = gh
        self.conn = conn
        self.rules = rules
        self.scan_id = scan_id
        self.max_requests = max_requests
        self.resume_hours = resume_hours
        self._start_count = gh.counters.code_search
        self.summary = Summary()

    # ---------- public ----------

    def run(self, families: list[Family], forks: bool = True) -> Summary:
        try:
            for fam in families:
                self.run_family(fam, forks=False)
                if forks and fam.forks:
                    self.run_family(fam, forks=True)
        except BudgetExhausted:
            self.summary.budget_exhausted = True
            log.warning("code-search budget exhausted; rerun to resume")
        return self.summary

    def run_family(self, fam: Family, forks: bool) -> None:
        base = fam.query + (" fork:only" if forks else "")
        log.info("family %s%s: %s", fam.id, " (forks)" if forks else "", base)
        self._sweep(fam, Slice(base=base), depth=0)

    # ---------- internals ----------

    def _used(self) -> int:
        return self.gh.counters.code_search - self._start_count

    def _check_budget(self) -> None:
        if self.max_requests is not None and self._used() >= self.max_requests:
            raise BudgetExhausted()

    def _is_done(self, fam: Family, q: str) -> bool:
        """A slice completed in this scan, or in any scan within `resume_hours`, is not re-fetched.

        This makes an interrupted nightly run resumable even though the rerun gets a new scan id.
        """
        row = self.conn.execute(
            """SELECT completed_at FROM slice_run
               WHERE family=? AND query=? AND completed_at IS NOT NULL
                 AND (scan_id=? OR completed_at >= strftime('%Y-%m-%dT%H:%M:%SZ','now', ?))
               ORDER BY completed_at DESC LIMIT 1""",
            (fam.id, q, self.scan_id, f"-{self.resume_hours} hours"),
        ).fetchone()
        return row is not None

    def _fetch_page(self, q: str, page: int) -> tuple[dict[str, Any], bool]:
        """Fetch one page; retry when the backend reports incomplete results."""
        incomplete = False
        for attempt in range(3):
            self._check_budget()
            res = self.gh.search_code(q, page=page, per_page=PER_PAGE)
            self.summary.pages += 1
            incomplete = bool(res.get("incomplete_results"))
            if not incomplete:
                return res, False
            log.warning("incomplete_results for %r page %d (attempt %d)", q, page, attempt + 1)
            time.sleep(5 * (attempt + 1))
        return res, True

    def _sweep(self, fam: Family, sl: Slice, depth: int) -> None:
        q = sl.query
        if self._is_done(fam, q):
            log.debug("skip (done): %s", q)
            return
        cap = self.rules.max_hits_per_slice
        try:
            first, incomplete = self._fetch_page(q, 1)
        except GitHubError as exc:
            self.summary.errors.append(f"{fam.id}: {q}: {exc}")
            log.error("%s: %s", q, exc)
            return
        total = int(first.get("total_count") or 0)
        items = list(first.get("items") or [])
        log.info("slice [%s] total≈%d%s depth=%d :: %s", fam.id, total, " (incomplete)" if incomplete else "", depth, q)

        if total > cap and depth < MAX_DEPTH:
            # store what we have (idempotent), then split
            self._store_hits(fam, items, sl)
            if self._split(fam, sl, items, depth):
                return
            log.warning("cannot split further; will paginate (over cap): %s", q)

        pages = 1
        short = len(items) < PER_PAGE
        all_items = items
        while not short and pages < MAX_PAGES:
            try:
                res, inc = self._fetch_page(q, pages + 1)
            except GitHubError as exc:
                self.summary.errors.append(f"{fam.id}: {q} p{pages + 1}: {exc}")
                log.error("%s page %d: %s", q, pages + 1, exc)
                break
            incomplete = incomplete or inc
            pages += 1
            page_items = list(res.get("items") or [])
            all_items.extend(page_items)
            short = len(page_items) < PER_PAGE

        accepted = self._store_hits(fam, all_items, sl)
        over_cap = not short
        if over_cap and depth < MAX_DEPTH and self._split(fam, sl, all_items, depth):
            # child slices cover it; record parent as split (completed, over_cap flagged for transparency)
            self._record(fam, q, pages, len(all_items), accepted, total, short, incomplete, over_cap=True)
            return
        self._record(fam, q, pages, len(all_items), accepted, total, short, incomplete, over_cap)

    def _split(self, fam: Family, sl: Slice, items: list[dict], depth: int) -> bool:
        """Try the family's slice axes in order. Returns True when child sweeps ran."""
        for axis in fam.slice_axes:
            if axis == "size":
                lo, hi = sl.size if sl.size else (self.rules.size_min, self.rules.size_max)
                if hi > lo:
                    mid = int(math.sqrt(max(lo, 1) * hi))
                    mid = min(max(mid, lo), hi - 1)
                    for rng in ((lo, mid), (mid + 1, hi)):
                        self._sweep(fam, Slice(sl.base, sl.extra, rng), depth + 1)
                    return True
            elif axis == "term":
                used = {t.removeprefix("NOT ").strip('"') for t in sl.extra}
                for term in self.rules.term_axis:
                    if term not in used:
                        for variant in (term, f"NOT {term}"):
                            self._sweep(fam, Slice(sl.base, sl.extra + (variant,), sl.size), depth + 1)
                        return True
            elif axis == "owner":
                owners = Counter(
                    (it.get("repository") or {}).get("owner", {}).get("login", "") for it in items
                )
                owners.pop("", None)
                excluded = {t[len("-user:"):] for t in sl.extra if t.startswith("-user:")}
                top = [o for o, _ in owners.most_common(6) if o not in excluded][:3]
                if top and not any(t.startswith("user:") for t in sl.extra):
                    for o in top:
                        self._sweep(fam, Slice(sl.base, sl.extra + (f"user:{o}",), sl.size), depth + 1)
                    rest = tuple(f"-user:{o}" for o in top)
                    self._sweep(fam, Slice(sl.base, sl.extra + rest, sl.size), depth + 1)
                    return True
        return False

    def _record(self, fam: Family, q: str, pages: int, items: int, accepted: int, total: int,
                short: bool, incomplete: bool, over_cap: bool) -> None:
        self.summary.slices += 1
        if incomplete:
            self.summary.slices_incomplete += 1
        if over_cap:
            self.summary.slices_over_cap += 1
        self.conn.execute(
            """INSERT OR REPLACE INTO slice_run
               (scan_id, family, query, pages_fetched, items, accepted, total_count, last_page_short, incomplete_results, over_cap, completed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (self.scan_id, fam.id, q, pages, items, accepted, total, int(short), int(incomplete), int(over_cap), now()),
        )
        self.conn.commit()

    def _store_hits(self, fam: Family, items: list[dict], sl: Slice) -> int:
        ts = now()
        accepted = 0
        is_fork_query = " fork:only" in sl.base
        for it in items:
            path = it.get("path") or ""
            repo = it.get("repository") or {}
            rid = repo.get("id")
            if rid is None:
                continue
            self.summary.items += 1
            if not fam.accepts(path):
                self.summary.rejected_path += 1
                continue
            accepted += 1
            owner = (repo.get("owner") or {})
            is_fork = int(bool(repo.get("fork")) or is_fork_query)
            self.conn.execute(
                """INSERT INTO repo (id, node_id, full_name, owner, owner_type, is_fork, status, first_seen, last_seen_in_search)
                   VALUES (?,?,?,?,?,?, 'candidate', ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     node_id=COALESCE(excluded.node_id, repo.node_id),
                     full_name=excluded.full_name, owner=excluded.owner, owner_type=excluded.owner_type,
                     is_fork=excluded.is_fork, last_seen_in_search=excluded.last_seen_in_search""",
                (rid, repo.get("node_id"), repo.get("full_name"), owner.get("login"), owner.get("type"), is_fork, ts, ts),
            )
            self.conn.execute(
                """INSERT INTO marker_hit (repo_id, marker_id, path, blob_oid, is_root, is_fork, first_seen, last_seen)
                   VALUES (?,?,?,?,1,?,?,?)
                   ON CONFLICT(repo_id, marker_id, path) DO UPDATE SET
                     blob_oid=excluded.blob_oid, is_fork=excluded.is_fork, last_seen=excluded.last_seen""",
                (rid, fam.id, path, it.get("sha"), is_fork, ts, ts),
            )
            self.summary.repos.add(rid)
        self.summary.accepted += accepted
        self.conn.commit()
        return accepted
