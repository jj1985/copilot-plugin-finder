import sqlite3

from cpf.db import migrate, now
from cpf.dedup import run_dedup


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    migrate(c)
    return c


def add_repo(c, rid, name, *, fork=0, parent=None, stars=0, tree=None, head=None, manifest=None, readme=None,
             created="2026-01-01", mk_name="m", archived=0, seed=None, owner_type="User"):
    owner = name.split("/")[0]
    c.execute(
        """INSERT INTO repo(id, node_id, full_name, owner, owner_type, is_fork, parent_id, parent_full_name, stars, forks, root_tree_oid, head_oid,
                            readme_oid, created_at, is_archived, status, evidence, kind, marketplace_name, effective_marketplace_path, listed_by_seed, first_seen)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active','verified-root','marketplace',?, '.github/plugin/marketplace.json', ?, ?)""",
        (rid, f"n{rid}", name, owner, owner_type, fork, parent, None, stars, 0, tree, head, readme, created, archived, mk_name, seed, now()),
    )
    if manifest:
        c.execute("INSERT INTO manifest_history(repo_id, path, blob_oid, first_seen, last_seen) VALUES (?, '.github/plugin/marketplace.json', ?, ?, ?)", (rid, manifest, now(), now()))
        c.execute("INSERT OR IGNORE INTO blob(oid, byte_size, first_seen) VALUES (?, 1500, ?)", (manifest, now()))
    if readme:
        c.execute("INSERT OR IGNORE INTO blob(oid, byte_size, first_seen) VALUES (?, 2000, ?)", (readme, now()))


def clusters(c):
    return {r["full_name"]: (r["cluster_id"], r["is_canonical"], r["diverged_fork"]) for r in c.execute("SELECT full_name, cluster_id, is_canonical, diverged_fork FROM repo")}


def test_fork_collapses_and_divergent_fork_stays_separate():
    c = _conn()
    add_repo(c, 1, "up/stream", stars=100, tree="t1", head="h1", manifest="m1", readme="r1", created="2025-01-01")
    add_repo(c, 2, "a/fork-same", fork=1, parent=1, tree="t1", head="h1", manifest="m1", readme="r1")          # pristine fork
    add_repo(c, 3, "b/fork-edited", fork=1, parent=1, tree="t3", head="h3", manifest="m3", readme="r1")        # edited, 0 stars -> noise copy
    add_repo(c, 4, "c/hard-fork", fork=1, parent=1, stars=50, tree="t4", head="h4", manifest="m4", readme="r4", mk_name="other")
    s = run_dedup(c, scan_id=1)
    cl = clusters(c)
    assert cl["up/stream"][1] == 1 and cl["a/fork-same"][0] == cl["up/stream"][0]
    assert cl["b/fork-edited"][0] == cl["up/stream"][0] and cl["b/fork-edited"][1] == 0
    assert cl["c/hard-fork"][0] != cl["up/stream"][0] and cl["c/hard-fork"][2] == 1 and cl["c/hard-fork"][1] == 1
    assert s.diverged_forks == 1
    canon = c.execute("SELECT network_size, indexed_copies FROM repo WHERE id=1").fetchone()
    assert canon["network_size"] == 2 and canon["indexed_copies"] == 0


def test_identical_tree_merges_detached_clones_and_prefers_oldest():
    c = _conn()
    add_repo(c, 1, "x/newer", tree="tt", head="h", manifest="m", created="2026-05-01", stars=3)
    add_repo(c, 2, "y/older", tree="tt", head="h", manifest="m", created="2025-05-01", stars=1)
    run_dedup(c, 1)
    cl = clusters(c)
    assert cl["x/newer"][0] == cl["y/older"][0]
    assert cl["y/older"][1] == 1 and cl["x/newer"][1] == 0


def test_single_strong_signal_is_similar_only_but_two_signals_merge():
    c = _conn()
    add_repo(c, 1, "p/one", tree="t1", head="h1", manifest="mm", readme="r1")
    add_repo(c, 2, "q/two", tree="t2", head="h2", manifest="mm", readme="r2")       # manifest only
    add_repo(c, 3, "r/three", tree="t3", head="h3", manifest="mm", readme="r1")     # manifest + readme with p/one
    s = run_dedup(c, 1)
    cl = clusters(c)
    assert cl["p/one"][0] != cl["q/two"][0]
    assert cl["p/one"][0] == cl["r/three"][0]
    sigs = {r[0] for r in c.execute("SELECT signal FROM edge")}
    assert {"manifest", "readme", "strong2"} <= sigs


def test_boilerplate_blob_gives_no_evidence():
    c = _conn()
    for i in range(7):  # 7 distinct non-fork owners share one manifest blob
        add_repo(c, i + 1, f"o{i}/starter", tree=f"t{i}", head=f"h{i}", manifest="boiler", readme=f"r{i}")
    s = run_dedup(c, 1)
    assert s.clusters == 7 and s.template_blobs == 1
    assert c.execute("SELECT COUNT(*) FROM edge WHERE signal='manifest'").fetchone()[0] == 0
    assert c.execute("SELECT is_template_blob FROM blob WHERE oid='boiler'").fetchone()[0] == 1


def test_diverged_fork_is_not_merged_back_by_shared_readme_and_plugins():
    c = _conn()
    add_repo(c, 1, "up/stream", stars=1000, tree="t1", head="h1", manifest="m1", readme="r1", created="2025-01-01")
    add_repo(c, 2, "me/hard-fork", fork=1, parent=1, stars=40, tree="t2", head="h2", manifest="m2", readme="r1", mk_name="mine")
    for rid, oid in ((1, "pt1"), (2, "pt1"), (1, "pt2"), (2, "pt2")):  # same plugin directories vendored
        c.execute("INSERT OR IGNORE INTO plugin(repo_id, name, dir_tree_oid) VALUES (?,?,?)", (rid, oid, oid))
    s = run_dedup(c, 1)
    cl = clusters(c)
    assert cl["me/hard-fork"][2] == 1
    assert cl["me/hard-fork"][0] != cl["up/stream"][0]
    assert c.execute("SELECT COUNT(*) FROM edge WHERE signal='strong2_blocked'").fetchone()[0] == 1


def test_template_family_is_recorded_not_merged():
    c = _conn()
    add_repo(c, 1, "t/template", tree="a", head="h1", manifest="m1")
    c.execute("UPDATE repo SET is_template=1 WHERE id=1")
    add_repo(c, 2, "u/generated", tree="b", head="h2", manifest="m2")
    c.execute("UPDATE repo SET template_id=1, template_full_name='t/template' WHERE id=2")
    run_dedup(c, 1)
    cl = clusters(c)
    assert cl["t/template"][0] != cl["u/generated"][0]
    assert c.execute("SELECT COUNT(*) FROM edge WHERE signal='template'").fetchone()[0] == 1
