"""cpf command line: discover | verify | golden | export | stats | scan."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import Settings
from .db import connect, finish_scan, start_scan
from .dedup import audit_report, run_dedup
from .discover import Discoverer
from .expand import Expander
from .export import export_all
from .gh import GitHub
from .golden import check_golden
from .markers import load_golden, load_rules
from .verify import Verifier


def _settings(args: argparse.Namespace) -> Settings:
    s = Settings()
    if args.db:
        s.db_path = Path(args.db)
    if args.rules:
        s.rules_dir = Path(args.rules)
    s.ensure_dirs()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return s


def _families(rules, args):
    groups = [g.strip() for g in args.group.split(",")] if getattr(args, "group", None) else None
    ids = [i.strip() for i in args.family.split(",")] if getattr(args, "family", None) else None
    fams = rules.select(groups=groups, ids=ids)
    if not fams:
        raise SystemExit("no families selected")
    return fams


def cmd_discover(args: argparse.Namespace) -> int:
    s = _settings(args)
    rules = load_rules(s.rules_dir)
    conn = connect(s.db_path)
    gh = GitHub(s.get_token())
    scan_id = args.scan_id or start_scan(conn, "discover")
    fams = _families(rules, args)
    d = Discoverer(gh, conn, rules, scan_id, max_requests=args.max_requests)
    summary = d.run(fams, forks=not args.no_forks)
    status = "partial" if summary.budget_exhausted or summary.errors else "ok"
    finish_scan(conn, scan_id, status, requests_used=gh.counters.as_dict(), repos_seen=len(summary.repos), errors=summary.errors[:50], notes=json.dumps(summary.as_dict()))
    print(json.dumps({"scan_id": scan_id, **summary.as_dict(), "requests": gh.counters.as_dict()}, indent=2))
    return 0 if status == "ok" else 2


def cmd_verify(args: argparse.Namespace) -> int:
    s = _settings(args)
    conn = connect(s.db_path)
    gh = GitHub(s.get_token())
    scan_id = args.scan_id or start_scan(conn, "verify")
    v = Verifier(gh, conn, scan_id, force=args.force)
    if args.names:
        res = v.verify_names([n.strip() for n in args.names.split(",") if n.strip()])
        conn.commit()
        print(json.dumps({k: (bool(val)) for k, val in res.items()}, indent=2))
    else:
        kwargs = {"statuses": [s.strip() for s in args.status.split(",")]} if args.status else {}
        v.verify_pending(limit=args.limit, **kwargs)
    finish_scan(conn, scan_id, "ok" if not v.summary.errors else "partial", requests_used=gh.counters.as_dict(), repos_verified=v.summary.repos_v1, errors=v.summary.errors[:50])
    print(json.dumps({"scan_id": scan_id, **v.summary.as_dict(), "requests": gh.counters.as_dict()}, indent=2))
    return 0


def cmd_expand(args: argparse.Namespace) -> int:
    s = _settings(args)
    conn = connect(s.db_path)
    gh = GitHub(s.get_token())
    scan_id = start_scan(conn, "expand")
    v = Verifier(gh, conn, scan_id)
    e = Expander(conn, v, scan_id)
    summary = e.run(max_rounds=args.max_rounds, max_repos=args.max_repos)
    finish_scan(conn, scan_id, "ok" if not (summary.errors or v.summary.errors) else "partial",
                requests_used=gh.counters.as_dict(), repos_verified=v.summary.repos_v1, errors=(summary.errors + v.summary.errors)[:50])
    print(json.dumps({"scan_id": scan_id, **summary.as_dict(), "verify": v.summary.as_dict(), "requests": gh.counters.as_dict()}, indent=2))
    return 0


def cmd_reclassify(args: argparse.Namespace) -> int:
    """Re-run facet/status computation from cached data after a rule change (no network)."""
    s = _settings(args)
    conn = connect(s.db_path)
    scan_id = start_scan(conn, "reclassify")
    v = Verifier(None, conn, scan_id)  # type: ignore[arg-type]
    n = v.reclassify(limit=args.limit)
    finish_scan(conn, scan_id, "ok", repos_verified=n)
    print(json.dumps({"scan_id": scan_id, "reclassified": n}))
    return 0


def cmd_dedup(args: argparse.Namespace) -> int:
    s = _settings(args)
    conn = connect(s.db_path)
    scan_id = start_scan(conn, "dedup")
    summary = run_dedup(conn, scan_id)
    out = s.root / "docs" / "dedup-audit.md"
    audit_report(conn, out)
    finish_scan(conn, scan_id, "ok", notes=json.dumps(summary.as_dict()))
    print(json.dumps({"scan_id": scan_id, **summary.as_dict(), "audit": str(out)}, indent=2))
    return 0


def cmd_golden(args: argparse.Namespace) -> int:
    s = _settings(args)
    conn = connect(s.db_path)
    golden = load_golden(s.rules_dir)
    verifier = None
    scan_id = None
    if not args.no_fetch:
        gh = GitHub(s.get_token())
        scan_id = start_scan(conn, "golden")
        verifier = Verifier(gh, conn, scan_id)
    res = check_golden(conn, verifier, golden)
    if scan_id is not None:
        finish_scan(conn, scan_id, "ok" if res["recall"] >= 1.0 else "partial", recall_golden=res["recall"])
    print(json.dumps(res, indent=2))
    return 0 if res["recall"] >= 1.0 else 3


def cmd_export(args: argparse.Namespace) -> int:
    s = _settings(args)
    conn = connect(s.db_path)
    meta = export_all(conn, s.export_dir)
    print(json.dumps(meta, indent=2, default=str))
    return 0


def cmd_site(args: argparse.Namespace) -> int:
    from .site_export import export_site
    s = _settings(args)
    conn = connect(s.db_path)
    out = Path(args.out) if args.out else s.root / "site" / "public" / "data"
    meta = export_site(conn, out)
    sizes = {p.name: p.stat().st_size for p in out.glob("*.json")}
    sizes["detail/*"] = sum(p.stat().st_size for p in (out / "detail").glob("*.json"))
    print(json.dumps({"out": str(out), "repos": meta["repos_active"], "plugins": meta["plugins"], "bytes": sizes}, indent=2))
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    s = _settings(args)
    conn = connect(s.db_path)
    out = {}
    out["repos_by_status"] = dict(conn.execute("SELECT status, COUNT(*) FROM repo GROUP BY status").fetchall())
    out["active_by_native_level"] = dict(conn.execute("SELECT native_level, COUNT(*) FROM repo WHERE status='active' GROUP BY native_level").fetchall())
    out["active_by_kind"] = dict(conn.execute("SELECT kind, COUNT(*) FROM repo WHERE status='active' GROUP BY kind").fetchall())
    out["active_by_format"] = dict(conn.execute("SELECT format, COUNT(*) FROM repo WHERE status='active' GROUP BY format").fetchall())
    out["hits_by_marker"] = dict(conn.execute("SELECT marker_id, COUNT(*) FROM marker_hit GROUP BY marker_id").fetchall())
    out["repos_by_marker"] = dict(conn.execute("SELECT marker_id, COUNT(DISTINCT repo_id) FROM marker_hit GROUP BY marker_id").fetchall())
    out["forks_active"] = conn.execute("SELECT COUNT(*) FROM repo WHERE status='active' AND is_fork=1").fetchone()[0]
    out["dual_format"] = conn.execute("SELECT COUNT(*) FROM repo WHERE status='active' AND dual_format=1").fetchone()[0]
    out["plugins"] = conn.execute("SELECT COUNT(*) FROM plugin").fetchone()[0]
    out["plugin_refs_external"] = conn.execute("SELECT COUNT(*) FROM plugin_ref").fetchone()[0]
    out["adopters"] = conn.execute("SELECT COUNT(DISTINCT repo_id) FROM adopter").fetchone()[0]
    out["blobs"] = conn.execute("SELECT COUNT(*) FROM blob").fetchone()[0]
    out["slices"] = dict(conn.execute("SELECT family, COUNT(*) FROM slice_run GROUP BY family").fetchall())
    out["slices_incomplete"] = conn.execute("SELECT COUNT(*) FROM slice_run WHERE incomplete_results=1 OR over_cap=1").fetchone()[0]
    out["top_repos"] = [dict(r) for r in conn.execute("SELECT full_name, stars, native_level, kind, plugin_count FROM repo WHERE status='active' ORDER BY stars DESC LIMIT 15")]
    out["last_scans"] = [dict(r) for r in conn.execute("SELECT id, kind, started, finished, status, repos_seen, repos_verified FROM scan ORDER BY id DESC LIMIT 5")]
    print(json.dumps(out, indent=2, default=str))
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    """discover -> verify -> golden -> export in one scan record."""
    s = _settings(args)
    rules = load_rules(s.rules_dir)
    conn = connect(s.db_path)
    gh = GitHub(s.get_token())
    scan_id = start_scan(conn, "scan")
    fams = _families(rules, args)
    d = Discoverer(gh, conn, rules, scan_id, max_requests=args.max_requests)
    dsum = d.run(fams, forks=not args.no_forks)
    v = Verifier(gh, conn, scan_id)
    v.verify_pending(limit=args.limit)
    esum = Expander(conn, v, scan_id).run(max_rounds=2) if not args.no_expand else None
    golden = check_golden(conn, v, load_golden(s.rules_dir))
    dd = run_dedup(conn, scan_id)
    audit_report(conn, s.root / "docs" / "dedup-audit.md")
    meta = export_all(conn, s.export_dir)
    errors = dsum.errors + v.summary.errors + (esum.errors if esum else [])
    status = "ok" if golden["recall"] >= 1.0 and not dsum.budget_exhausted and not errors else "partial"
    finish_scan(conn, scan_id, status, requests_used=gh.counters.as_dict(), repos_seen=len(dsum.repos),
                repos_verified=v.summary.repos_v1, errors=errors[:50], recall_golden=golden["recall"],
                notes=json.dumps({"discover": dsum.as_dict(), "verify": v.summary.as_dict()}))
    print(json.dumps({"scan_id": scan_id, "status": status, "discover": dsum.as_dict(), "verify": v.summary.as_dict(),
                      "expand": esum.as_dict() if esum else None, "dedup": dd.as_dict(),
                      "golden": {k: golden[k] for k in ("recall", "hits", "total")},
                      "golden_misses": [r for r in golden["results"] if not r["ok"]],
                      "export": {"repos": meta["repos"], "plugins": meta["plugins"]},
                      "requests": gh.counters.as_dict()}, indent=2, default=str))
    return 0 if status == "ok" else 2


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="cpf", description="Copilot Plugin Finder scanner")
    p.add_argument("--db", help="SQLite path (default data/index.sqlite)")
    p.add_argument("--rules", help="rules directory (default rules/)")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_select(sp):
        sp.add_argument("--group", help="comma-separated groups: copilot-authored,claude-format,pointers")
        sp.add_argument("--family", help="comma-separated family ids")
        sp.add_argument("--no-forks", action="store_true", help="skip fork:only passes")
        sp.add_argument("--max-requests", type=int, help="cap on code-search requests this run")

    sp = sub.add_parser("discover", help="run code-search sweeps")
    add_select(sp)
    sp.add_argument("--scan-id", type=int)
    sp.set_defaults(func=cmd_discover)

    sp = sub.add_parser("verify", help="GraphQL verification of candidates")
    sp.add_argument("--limit", type=int)
    sp.add_argument("--force", action="store_true", help="ignore head-oid gate")
    sp.add_argument("--status", help="comma-separated statuses to (re)verify, e.g. invalid,no-manifest")
    sp.add_argument("--names", help="comma-separated owner/repo to verify directly")
    sp.add_argument("--scan-id", type=int)
    sp.set_defaults(func=cmd_verify)

    sp = sub.add_parser("expand", help="follow marketplace/adopter/parent references to unseen repos")
    sp.add_argument("--max-rounds", type=int, default=3)
    sp.add_argument("--max-repos", type=int)
    sp.set_defaults(func=cmd_expand)

    sp = sub.add_parser("reclassify", help="recompute facets from cached blobs after a rule change (no network)")
    sp.add_argument("--limit", type=int)
    sp.set_defaults(func=cmd_reclassify)

    sp = sub.add_parser("dedup", help="compute edges, clusters and canonical repos; write docs/dedup-audit.md")
    sp.set_defaults(func=cmd_dedup)

    sp = sub.add_parser("golden", help="check golden recall set")
    sp.add_argument("--no-fetch", action="store_true", help="do not verify missing golden repos")
    sp.set_defaults(func=cmd_golden)

    sp = sub.add_parser("export", help="write JSON exports")
    sp.set_defaults(func=cmd_export)

    sp = sub.add_parser("site", help="write columnar JSON for the static site (site/public/data)")
    sp.add_argument("--out")
    sp.set_defaults(func=cmd_site)

    sp = sub.add_parser("stats", help="print database statistics")
    sp.set_defaults(func=cmd_stats)

    sp = sub.add_parser("scan", help="discover + verify + expand + golden + dedup + export")
    add_select(sp)
    sp.add_argument("--limit", type=int, help="max repos to verify")
    sp.add_argument("--no-expand", action="store_true")
    sp.set_defaults(func=cmd_scan)

    args = p.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
