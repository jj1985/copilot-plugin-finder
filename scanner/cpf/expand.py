"""Graph expansion (PLAN.md §3.3): follow marketplace `source` references, adopter settings
references and fork parents to repos that search did not return, verify them, then compute
reverse-reference counts.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field

from .db import now
from .verify import Verifier

log = logging.getLogger("cpf.expand")

SEEDS = ("github/awesome-copilot", "github/copilot-plugins")


@dataclass
class ESummary:
    rounds: int = 0
    referrals: int = 0
    verified: int = 0
    found: int = 0
    missing: int = 0
    errors: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return dict(self.__dict__)


class Expander:
    def __init__(self, conn: sqlite3.Connection, verifier: Verifier, scan_id: int) -> None:
        self.conn = conn
        self.v = verifier
        self.scan_id = scan_id
        self.summary = ESummary()

    # ---------- frontier ----------

    def record_referrals(self) -> int:
        """Materialise referral rows from plugin_ref, adopter and fork-parent relations."""
        ts = now()
        n = 0
        n += self.conn.execute(
            """INSERT OR IGNORE INTO referral(full_name_lc, kind, from_repo_id, path, first_seen)
               SELECT lower(target_repo), 'plugin_ref', marketplace_repo_id, COALESCE(target_path,''), ? FROM plugin_ref
               WHERE target_repo LIKE '%/%' AND target_repo NOT LIKE '%:%'""", (ts,)).rowcount
        n += self.conn.execute(
            """INSERT OR IGNORE INTO referral(full_name_lc, kind, from_repo_id, path, first_seen)
               SELECT lower(marketplace_ref), 'adopter', repo_id, '', ? FROM adopter
               WHERE marketplace_ref LIKE '%/%' AND marketplace_ref NOT LIKE '%:%' AND marketplace_ref NOT LIKE 'http%'""", (ts,)).rowcount
        n += self.conn.execute(
            """INSERT OR IGNORE INTO referral(full_name_lc, kind, from_repo_id, path, first_seen)
               SELECT lower(parent_full_name), 'parent', id, '', ? FROM repo
               WHERE status='active' AND is_fork=1 AND parent_full_name IS NOT NULL""", (ts,)).rowcount
        self.conn.commit()
        return n

    def frontier(self) -> list[str]:
        rows = self.conn.execute(
            """SELECT DISTINCT r.full_name_lc FROM referral r
               LEFT JOIN repo p ON lower(p.full_name)=r.full_name_lc
               WHERE p.id IS NULL AND r.full_name_lc NOT IN (SELECT key FROM deny)
               ORDER BY r.full_name_lc"""
        ).fetchall()
        return [r[0] for r in rows if _valid_name(r[0])]

    # ---------- run ----------

    def run(self, max_rounds: int = 3, max_repos: int | None = None) -> ESummary:
        for rnd in range(max_rounds):
            self.summary.referrals += self.record_referrals()
            names = self.frontier()
            if max_repos is not None:
                names = names[:max_repos]
            if not names:
                break
            self.summary.rounds += 1
            log.info("expansion round %d: %d repos to verify by name", rnd + 1, len(names))
            # subdirectories referenced as owner/repo:path
            self.v.extra_dirs = {}
            for r in self.conn.execute("SELECT full_name_lc, path FROM referral WHERE kind='plugin_ref' AND path!=''"):
                self.v.extra_dirs.setdefault(r[0], set()).add(r[1])
            res = self.v.verify_names(names)
            self.conn.commit()
            found = sum(1 for n in res.values() if n)
            self.summary.verified += len(res)
            self.summary.found += found
            self.summary.missing += len(res) - found
            # record unresolved names so the UI can show "declared but not found"
            ts = now()
            for name, node in res.items():
                if node is None:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO deny(key, reason, created_at) VALUES (?, 'expand: not found or inaccessible', ?)",
                        (name, ts),
                    )
            self.conn.commit()
        self.resolve_and_count()
        return self.summary

    # ---------- reverse references ----------

    def resolve_and_count(self) -> None:
        c = self.conn
        c.execute("UPDATE plugin_ref SET target_repo_id=(SELECT id FROM repo WHERE lower(full_name)=lower(plugin_ref.target_repo))")
        c.execute("UPDATE plugin SET source_repo_id=(SELECT id FROM repo WHERE lower(full_name)=lower(plugin.source_repo)) WHERE source_repo IS NOT NULL")
        c.execute("UPDATE repo SET referenced_by_marketplaces=0, referenced_by_settings=0, listed_by_seed=NULL")
        # distinct non-fork marketplaces that list the repo (forks of awesome-copilot would otherwise inflate it)
        c.execute(
            """UPDATE repo SET referenced_by_marketplaces=(
                 SELECT COUNT(DISTINCT p.marketplace_repo_id) FROM plugin_ref p JOIN repo m ON m.id=p.marketplace_repo_id
                 WHERE p.target_repo_id=repo.id AND m.is_fork=0)"""
        )
        c.execute(
            """UPDATE repo SET referenced_by_settings=(
                 SELECT COUNT(DISTINCT a.repo_id) FROM adopter a WHERE lower(a.marketplace_ref)=lower(repo.full_name))"""
        )
        for seed in SEEDS:
            c.execute(
                """UPDATE repo SET listed_by_seed=CASE WHEN listed_by_seed IS NULL THEN ? ELSE listed_by_seed||','||? END
                   WHERE id IN (SELECT p.target_repo_id FROM plugin_ref p JOIN repo m ON m.id=p.marketplace_repo_id WHERE lower(m.full_name)=? AND p.target_repo_id IS NOT NULL)""",
                (seed, seed, seed),
            )
        c.commit()


def _valid_name(name: str) -> bool:
    parts = name.split("/")
    return len(parts) == 2 and all(p and all(ch.isalnum() or ch in "-._" for ch in p) for p in parts) and not name.endswith(".git")
