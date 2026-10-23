"""Verifier unit tests with an in-memory database and a stub GitHub client (no network)."""

import sqlite3

from cpf.db import migrate, now
from cpf.verify import Batcher, Verifier


class StubGH:
    def __init__(self):
        self.calls = []

    def graphql(self, query, variables=None):
        self.calls.append((query, variables))
        return {"nodes": []}


def _conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    migrate(c)
    return c


def _node(db_id, node_id, name, head="a" * 40):
    return {
        "__typename": "Repository", "id": node_id, "databaseId": db_id, "nameWithOwner": name,
        "owner": {"__typename": "User", "login": name.split("/")[0]},
        "defaultBranchRef": {"name": "main", "target": {"oid": head, "committedDate": "2026-01-01T00:00:00Z",
                                                        "tree": {"oid": "t" * 40, "entries": []}}},
        "repositoryTopics": {"nodes": []},
    }


def test_legacy_node_id_is_not_marked_gone():
    c = _conn()
    ts = now()
    # discovered via REST search with a legacy-format node id
    c.execute("INSERT INTO repo(id, node_id, full_name, status, first_seen) VALUES (1, 'MDEwOlJlcG9zaXRvcnkx', 'o/r', 'candidate', ?)", (ts,))
    c.execute("INSERT INTO repo(id, node_id, full_name, status, first_seen) VALUES (2, 'MDEwOlJlcG9zaXRvcnky', 'o/gone', 'candidate', ?)", (ts,))
    v = Verifier(StubGH(), c, scan_id=1)
    v._run_v2 = lambda nodes: None  # not under test
    # GraphQL answers with the new-format id for repo 1 only; repo 2 is genuinely missing
    v._after_v1([_node(1, "R_kgDOAAAAAQ", "o/r")], expected_ids=["MDEwOlJlcG9zaXRvcnkx", "MDEwOlJlcG9zaXRvcnky"])
    rows = {r["id"]: r for r in c.execute("SELECT id, status, node_id FROM repo")}
    assert rows[1]["status"] != "gone"
    assert rows[1]["node_id"] == "R_kgDOAAAAAQ"  # refreshed to the id GraphQL uses
    assert rows[2]["status"] == "gone"
    assert v.summary.repos_gone == 1


def test_unchanged_head_skips_v2():
    c = _conn()
    ts = now()
    c.execute("INSERT INTO repo(id, node_id, full_name, status, first_seen) VALUES (1, 'n1', 'o/r', 'active', ?)", (ts,))
    c.execute("INSERT INTO repo_state(repo_id, head_oid, root_tree_oid, verified_at, v2_done) VALUES (1, ?, ?, ?, 1)", ("a" * 40, "t" * 40, ts))
    v = Verifier(StubGH(), c, scan_id=1)
    called = []
    v._run_v2 = lambda nodes: called.append(len(nodes))
    v._after_v1([_node(1, "n1", "o/r")], expected_ids=["n1"])
    assert called == [] and v.summary.repos_unchanged == 1
    v._after_v1([_node(1, "n1", "o/r", head="b" * 40)], expected_ids=["n1"])
    assert called == [1]


def test_batcher_never_regrows_past_a_timeout():
    b = Batcher(50, max_size=50)
    b.shrink()
    assert b.size == 25 and b.ceiling == 49
    for _ in range(60):
        b.grow()
    assert b.size <= 49
    b.shrink()
    assert b.ceiling < 49
