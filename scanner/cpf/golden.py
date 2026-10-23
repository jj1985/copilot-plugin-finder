"""Golden recall set check (PLAN.md §3.6)."""

from __future__ import annotations

import logging
import sqlite3

from .verify import Verifier

log = logging.getLogger("cpf.golden")

RANK = {"declared-only": 0, "verified-nested": 1, "verified-root": 2}


def check_golden(conn: sqlite3.Connection, verifier: Verifier | None, golden: list[dict]) -> dict:
    results = []
    missing_names = []
    for g in golden:
        row = conn.execute("SELECT id, full_name, status, evidence, kind FROM repo WHERE lower(full_name)=lower(?)", (g["repo"],)).fetchone()
        if not row and verifier is not None:
            missing_names.append(g["repo"])
    if missing_names and verifier is not None:
        log.info("golden: %d repos not discovered, verifying directly", len(missing_names))
        verifier.verify_names(missing_names)
        conn.commit()
    hits = 0
    for g in golden:
        row = conn.execute("SELECT id, full_name, status, evidence, kind FROM repo WHERE lower(full_name)=lower(?)", (g["repo"],)).fetchone()
        expect = g.get("expect", "verified-root")
        found_in_search = bool(row and conn.execute("SELECT 1 FROM marker_hit WHERE repo_id=?", (row["id"],)).fetchone())
        ok = bool(row and row["status"] == "active" and RANK.get(row["evidence"] or "declared-only", 0) >= RANK.get(expect, 2))
        if expect == "declared-only":
            ok = bool(row)
        hits += int(ok)
        results.append({
            "repo": g["repo"], "expect": expect, "ok": ok,
            "status": row["status"] if row else None, "evidence": row["evidence"] if row else None,
            "kind": row["kind"] if row else None, "found_in_search": found_in_search,
        })
    recall = hits / len(golden) if golden else 1.0
    return {"recall": recall, "hits": hits, "total": len(golden), "results": results}
