# Phase 0b spike results (2026-10-22)

All probes run live against api.github.com with the `jj1985` token.

| Item | Result | Consequence |
|---|---|---|
| `path:/` root anchoring | `path:/.github/plugin filename:marketplace.json user:jj1985` returns only the two root-level repos; the nested `jj1985/worktools/soar-toolkit/.github/plugin/marketplace.json` is excluded. | Root-anchored queries are used for every family; the exact-path regex stays as a second guard. |
| `-user:` / `-org:` negation | `path:/.github/plugin filename:marketplace.json -org:microsoft` = 848 vs 888 (microsoft alone 28). | Owner carve-outs are a valid partition axis (`owner` in `slice_axes`). |
| `NOT term` partition | `... strict` = 47, `... NOT strict` = 820, total 888 (counts are estimates). | Term axis implemented as `q term` / `q NOT term`. |
| Fuzzy `filename:` | `filename:marketplace.json path:/` page 1 contained `kimi-marketplace.json`, `umbraco-marketplace.json`. | Hit filter on exact basename + path before any `marker_hit` row. |
| text-match media type | `Accept: application/vnd.github.text-match+json` on `"copilot plugin marketplace add" extension:md` (4,488 hits) returns fragments such as `copilot plugin marketplace add QoderAI/better-harness`. | S-README extraction can parse `owner/repo` from fragments without fetching files (Phase 2). |
| GraphQL batch size | Reviewer measured 502s at 25/50/100 repos × 8 blob lookups; tree-only 50 repos ≈ 5.4 s. Our two-stage run: V1 50/query, V2a 15/query, V2b 10/query, all adaptive (halve on 502). | Implemented in `verify.py` (`Batcher`). |
| First-commit cursor | Base64 cursor is rejected (`INVALID_CURSOR_ARGUMENTS`); the plain string `"<head_oid> <totalCount-2>"` works: `history(first:1, after:"b0216d… 85")` returned the `Initial commit` of `github/copilot-plugins`, matching REST `commits?per_page=1&page=87`. | Cheap first-commit signal available for Phase 2 de-dup (one GraphQL call per candidate pair). |
| `incomplete_results` | Observed once by a reviewer on `search/repositories`. | `Discoverer._fetch_page` retries up to 3× with backoff and records the flag per slice. |
| `GITHUB_TOKEN` in Actions for `search/code` | Not testable without a repository; the workflow in `.github/workflows/scan.yml` uses a `CPF_GITHUB_TOKEN` secret (fine-grained PAT) and falls back to `GITHUB_TOKEN` only if the secret is absent. | Open question 3 remains; test on first push. |
| Pages `.gz` handling | Not tested (no Pages site yet). | Export writes plain `.json`. |
