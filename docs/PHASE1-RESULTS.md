# Phase 1 results: first full census (2026-10-22)

Groups scanned: `copilot-authored` (6 marker families, source + fork passes) and `pointers`
(3 consumer-side settings families). The Claude-format group was not scanned.

## Numbers

| Measure | Value |
|---|---|
| Code-search requests (discovery, both runs) | ~330 over ~30 min wall-clock at 10/min |
| Candidate repos from search | 11,020 (19 hits rejected by the exact-path filter) |
| Active (valid effective manifest at HEAD) | 6,694 |
| &nbsp;&nbsp;Copilot-authored | 5,965 (4,079 non-fork) |
| &nbsp;&nbsp;Copilot-installable, Claude format only | 729 (found via settings-file or root hits) |
| &nbsp;&nbsp;kind: marketplace / plugin / both | 2,235 / 1,685 / 2,774 |
| &nbsp;&nbsp;format: agent-plugins-1.0 / 1.1 / legacy / claude | 2,915 / 7 / 2,854 / 918 |
| &nbsp;&nbsp;dual format (`.github/plugin` + `.claude-plugin`) | 3,432 |
| &nbsp;&nbsp;forks among active | 1,883 |
| Adopters (settings files naming marketplaces, no manifest) | 4,203 repos, 4,958 adopter rows |
| Invalid (manifest present, Copilot would reject) | 32 (e.g. wrong Agent Plugins `$schema` URL, broken JSON) |
| No usable file at HEAD | 90 (settings hits whose file names no marketplace) |
| Gone | 1 |
| Plugin rows (marketplace entries, before de-dup) | 53,111 (awesome-copilot forks dominate) |
| External plugin references (`source: github`) | 10,326 |
| Cached blobs | ~20k |
| Golden recall | 16/16 |

Export: `data/export/repos.json` (12 MB), `plugins.json` (26 MB), `meta.json`.

## Verification cost (measured)

- V1 with root tree + topics + release at 40–50 repos per query times out often; the adaptive
  batcher settled at 18–30 repos. 9,247 repos took ~65 min end to end on the first pass
  (V1 + V2a + V2b for everything).
- A refresh pass over 6,739 already-verified repos (V1 only, head oid unchanged) took 19 min.
- GraphQL points were never the constraint (~1,200 points for the whole run).

Phase 1 exit criterion "nightly run under 30 minutes" is therefore **not met** for the full
Copilot-authored + pointers set: discovery alone fits (~25 min), but discovery + refresh is
~45 min. Options: run discovery and refresh on alternating nights, drop `repositoryTopics`
and `latestRelease` from V1 into V2, or run two token budgets. Decision deferred to Phase 4.

## Defects found and fixed during the run

1. **Node-ID formats differ between REST and GraphQL.** Search returns legacy ids
   (`MDEw…`) for older repos; GraphQL returns `R_kgDO…`. Comparing them marked 8,053
   verified repos "gone". Fixed by comparing `databaseId`; regression test added.
2. **Non-JSON 2xx GraphQL responses** crashed the run. Now treated as a timeout (batch shrinks).
3. **Batch size oscillation** after timeouts wasted points. The batcher now remembers a ceiling.
4. **Partial V2 failures** finalised repos with empty data. Failed repos stay `candidate`.
5. **Git symlinks**: `OpenHands/extensions/.plugin/marketplace.json` and ~15 others are
   symlinks (blob = target path). The target blob is now fetched and parsed, with a warning
   that Windows checkouts may break.
6. **Local-file marketplaces** in `.claude/settings.json` (`source: "file"`) were dropped;
   they now count as adoption (`file:<path>` refs).
7. **`hooks` is not a Copilot-authorship signal** (Claude plugins have hooks too); only
   `extensions`, LSP, `com.github.copilot/` and Copilot paths are.

## Observations worth carrying into Phase 2

- Search estimates undercount: `.github/plugin/marketplace.json` reported 888 but paginating
  the source pass plus the fork pass yielded 1,989 distinct repos.
- 729 "Claude-format only" actives are mostly repos that also carry `.claude/settings.json`;
  they are legitimately installable by Copilot and belong in the toggle view.
- Top-starred "plugin" repos are often large projects that merely ship a manifest
  (`payloadcms/payload`, `saadeghi/daisyui`); a "repo is primarily a plugin" heuristic
  (manifest-related files as a share of the root tree) would help the default sort.
- The 90 `no-manifest` rows are settings files whose `extraKnownMarketplaces` is empty or
  unparseable JSONC; they can be ignored or re-checked monthly.
