# Review synthesis: PLAN.md v1 → v2

Date: 2026-10-22. Reviewers: Claude Opus (`review-opus.md`) and Claude Sonnet (`review-sonnet.md`), both run as independent subagents with read-only `gh` access and web search, both given the same brief. The v1 text they reviewed is preserved as `PLAN-v1-as-reviewed.md`. Where a reviewer made a live-verifiable claim that changed a design decision, I re-verified it myself before accepting; those checks are noted.

Legend: **A** accepted as proposed, **M** accepted with modification, **R** rejected or deferred, **O** moved to open questions.

## 1. Plugin markers

| # | Suggestion | Source | Decision | Why / change in v2 |
|---|---|---|---|---|
| 1.1 | Agent Plugins manifests require both `$schema` and `name`; v1 said only `name` | both | **A** | Confirmed against the CLI reference and spec §5.3. §2.1 corrected; the verifier enforces `$schema` on the Agent Plugins branch. |
| 1.2 | "Closed field set" is not a rejection criterion; unknown fields are reported and ignored | both | **A** | §2.1: `$schema` is the only format distinguisher; unknown fields become `schema_warnings`. |
| 1.3 | `filename:` in code search is fuzzy (`umbraco-marketplace.json`, `.agent-marketplace.json`, `kimi-marketplace.json`) | both | **A** | Re-verified myself: `filename:marketplace.json path:/` page 1 contained `kimi-marketplace.json` and `umbraco-marketplace.json`. §3.4 now starts with an exact basename + exact path filter before any hit becomes a `marker_hit`. |
| 1.4 | Use `path:/` for root-only queries instead of the `-path:` exclusion chain (root `marketplace.json plugins owner` = 399; root Agent Plugins manifest ≈ 2,450) | both | **A** | Re-verified: `path:/ filename:plugin.json agent-plugins.org` = 2,456; `path:/.github/plugin filename:marketplace.json` = 888. Marker table rewritten with root-anchored queries; `path:DIR` matches subdirectories too, so exact-path check remains. |
| 1.5 | Add legacy/entry fields `category`, `tags`, `strict`, entry-level `commands/agents/skills/hooks/mcpServers/lspServers`; `strict:false` means the marketplace entry *is* the manifest, so build the plugin inventory from marketplace entries first | Opus (Sonnet: "inline plugins") | **A** | §4.2 inventory now starts from marketplace entries; missing `plugin.json` is not an error. |
| 1.6 | `metadata.pluginRoot` must be applied when resolving relative `source` paths | Sonnet | **A** | Added to §4.2. |
| 1.7 | Manifest shadowing: a stray root `plugin.json`/`marketplace.json` from another ecosystem precedes the real manifest in CLI lookup order; record `effective_manifest_path` and `shadowed_manifests[]` | Opus | **A** | Added to §2.1 and the schema; "effective manifest invalid, valid manifest shadowed" is a warning. Whether the CLI falls through on parse failure is an open question. |
| 1.8 | Non-default-branch marketplaces (`owner/repo#ref`) are registrable but invisible to code search | Sonnet | **A** | Added to §9 false negatives; `ref` recorded when a settings file or README snippet names one. |
| 1.9 | Replace tiers A–D with orthogonal facets (`kind`, `native_level`, `evidence`, `dual_format`) and rename so Claude-format is not read as "not Copilot" | Sonnet (facets), Opus (naming) | **A** | §2.3 rewritten: facets are stored; the default view is a derived filter ("Copilot-authored, verified at root"); Claude-format is labelled "Copilot-installable (Claude format)". |
| 1.10 | Add `executes_code` (hooks, MCP commands, LSP, extensions, scripts) as a first-class attribute and filter | both | **A** | §4.1 derived fields, §7.2 filters and badges. |
| 1.11 | Per-surface support matrix (CLI / VS Code / app / cloud agent) and a `surfaces[]` field | Opus | **M** | Added as a small matrix with "docs / observed / unknown" cells and a `surfaces[]` field, but the scanner only asserts CLI installability in v1; the rest is open question 8. Building a full matrix now would be speculation. |
| 1.12 | Docs contradict each other on default marketplaces | Opus | **A** | Both statements recorded with URLs in §2.1. |
| 1.13 | Root `SKILL.md` fallback for legacy plugins counts as a skill | Opus | **A** | Added to §4.2. |
| 1.14 | `gh skill` skills-only repos are adjacent but not plugins | Sonnet | **A** | Listed as a non-goal with a `skills_only_repo` attribute possible later. |
| 1.15 | Strip emails from exports | both | **A** | §4.3 and §9: emails never leave SQLite. |

## 2. Discovery

| # | Suggestion | Source | Decision | Why / change in v2 |
|---|---|---|---|---|
| 2.1 | Arithmetic error: 450 requests at 10/min is 45 minutes, not 8 hours; a realistic Tier C sweep is ~1,000 requests ≈ 1.7 h | Sonnet | **A** | Correct; v1 multiplied wrongly. §3.2 budget rewritten. |
| 2.2 | `sort=indexed` is documented as "closing down"; do not make it the incremental backbone | both | **A** | §3.2: full sweeps are the primary path; `sort=indexed` kept as best-effort with a health check. |
| 2.3 | Tier C cadence: nightly full sweep (Sonnet) vs incremental + monthly full (Opus) | both, conflicting | **M** | Chosen: Tier A/B nightly; Tier C full sweep every 2–3 nights (≈2 h each) because it is cheap enough and avoids depending on a deprecated sort; direct GraphQL refresh of known repos is separate (see 5.1). |
| 2.4 | Split discovery from refresh: refresh known repos directly over GraphQL, search only discovers | Opus | **A** | New §3.5 and §6. |
| 2.5 | New vectors: `.claude/settings.json extraKnownMarketplaces` (4,104), README `"copilot plugin marketplace add"` (4,632), `.vscode/settings.json chat.plugins.marketplaces` (19), repo search `in:readme` with date filters | both | **A** | Added as S-SET-CL, S-README, S-VSC, R-README. S-README is the largest secondary vector found. |
| 2.6 | `-user:`/`-org:` negation works; use it for top-owner carve-outs | both (Opus unsure) | **A** | Re-verified myself: `-org:microsoft` dropped the root-marketplace count from 888 to 848 (microsoft has 28). v1's claim that it is unsupported was wrong. |
| 2.7 | Content-term complements (`"$schema"`, `strict`, `mcpServers`) as an extra partition axis because same-template manifests share one byte size | Sonnet | **A** | Added to §3.2. |
| 2.8 | Handle `incomplete_results: true` and regressing totals as retry-and-flag; persist per-slice completeness | Sonnet | **A** | `slice_run` table and retry rule added. |
| 2.9 | Archived repos, >1 year inactive repos and huge repos are not code-searchable by design | both | **A** | Added to §3.1 and the drop-out logic; graph expansion and direct re-verification cover them. |
| 2.10 | Fork census: code search sees 419 of 5,191 awesome-copilot forks; use `forkCount` and, for divergent forks, GraphQL `forks(orderBy STARGAZERS)` on canonical repos | Opus | **A** | §3.1 note and §5.1 signal list. |
| 2.11 | Documented fork-indexing rule (fork must outrank parent) is contradicted by observation | Sonnet | **A** | Recorded as "docs vs observed"; no rule encoded. |
| 2.12 | `text-match` media type to pull `owner/repo` tokens from search fragments without fetching files | Opus | **A** | Added to §3.3 (recalled by reviewer; cheap to try in Phase 0b). |
| 2.13 | Golden recall set (seed-referenced repos, user's repos) asserted every run; capture–recapture coverage estimate shown in UI | both | **M** | Golden set adopted in Phase 1. Capture–recapture adopted as an *indicative* number with an explicit caveat: both captures over-sample popular repos, so independence does not hold and the estimate is a lower bound on the population. Sourcegraph kept only as an optional free diagnostic. |
| 2.14 | GH Archive `CreateEvent`/`ForkEvent` name heuristics as cheap candidates | Opus | **M** | Listed as optional Phase 5 work; the claim that PushEvent payloads were trimmed in 2025 is unverified and noted as such. |
| 2.15 | "Repository search examines up to 4,000 repos" wording | Sonnet | **A** | Wording updated; retrievable cap still 1,000. |

## 3. Metadata

| # | Suggestion | Source | Decision | Why / change in v2 |
|---|---|---|---|---|
| 3.1 | The v1 GraphQL batch (50 repos × 8 blob lookups with text) does not work: 502 timeouts at 25/50/100, and timeouts still consume points; tree-only at 50 repos takes ~5.4 s | Opus (measured), Sonnet (predicted) | **A** | §3.4 rewritten as two-stage verification: V1 root-tree gate at ~50 repos/query skipped when head oid unchanged; V2 targeted blob fetch at 10–20 repos/query for changed repos only; adaptive batch sizing; "250k/hour" removed. |
| 3.2 | Content-addressed `blob` table keyed by git blob oid | both | **A** | Added; 5,191 awesome-copilot forks share one manifest row. |
| 3.3 | Add `templateRepository`, GraphQL node `id`, `archivedAt`, `isEmpty`, `isLocked`, head commit `committedDate` | Opus | **A** | Added to §4.1. |
| 3.4 | Add reverse-reference counts (`referenced_by_marketplaces`, `referenced_by_settings`) as an adoption signal | Opus | **A** | Added; also answers open question 5. |
| 3.5 | Add plugin-dir tree oid and SKILL.md blob oid per plugin/skill | both | **A** | Added; primary plugin-level de-dup keys. |
| 3.6 | Add `pinned` (40-char `sha`) status for external sources, `source_kind` open enum + `source_host`, `last_commit_touching_manifest` | Sonnet, Opus | **A** / **M** | First two added. `last_commit_touching_manifest` only for canonical Tier A/B repos (extra call). |
| 3.7 | Drop or defer: emails, `watchers`, `diskUsage`, `isDisabled` (display), `updatedAt`, `history.totalCount` except canonical repos | both | **A** | Done. |
| 3.8 | README: pick the real filename from the root tree (`readme.md`, `README.rst`), excerpt ~300 chars text-only | both | **A** | Done. |
| 3.9 | Per-skill rows for Tier C are too many for too little | Sonnet | **A** | Skills table limited to Copilot-authored and starred Claude-format repos. |
| 3.10 | `raw.githubusercontent.com` with immutable commit SHA as a points-free blob fallback | Opus | **M** | Noted as optional; IP-rate-limited. |

## 4. De-duplication

| # | Suggestion | Source | Decision | Why / change in v2 |
|---|---|---|---|---|
| 4.1 | Boilerplate guard: a blob oid shared by >3 unrelated owners or under ~300 bytes gives no evidence; same for near-empty identical root trees | both | **A** | `template_blob` table; §5.1 signals re-ranked. |
| 4.2 | Plain union-find only on definitive edges (fork, `templateRepository`, non-trivial identical root tree); other signals become `similar_to` edges with stored evidence; two independent strong edges to join | both | **A** | §5.2 rewritten; every cluster is explainable from `edge` rows. |
| 4.3 | Divergent-fork split: do not collapse a maintained hard fork under a dead parent | both | **A** | Split rule: manifest oid differs AND (own stars ≥ X, or marketplace name differs, or listed by a seed). Shown as "fork of Y". |
| 4.4 | Cluster tier/facets = union over members so a Claude-format canonical with a Copilot-native member stays in the default view | Opus | **A** | Added; important UX bug avoided. |
| 4.5 | Canonical rule 0: active, not archived, valid effective manifest; seed pointer above manifest `repository` field; `evidence=verified-root` over nested | both | **A** | §5.3 reordered. |
| 4.6 | GraphQL has no `source` field; walk `parent` 2–3 levels or one REST call per cluster root | both | **A** | Stated in §5.3. |
| 4.7 | Signal 5 (manifest identity by name+version+description) merges `my-plugin 1.0.0`; gate with tree oid or entropy | Sonnet | **A** | Demoted to medium and gated. |
| 4.8 | "Distribution is not duplication": a marketplace listing a source repo is never an edge | Opus | **A** | Stated explicitly. |
| 4.9 | `cluster_overrides.yaml` for manual merges/splits that survive rescans; stratified 100-cluster audit with per-signal precision | Sonnet | **A** | Added to Phase 2 deliverables. |
| 4.10 | Define `clone_count` vs `known_forks_count` to avoid double counting: show "network size" and "indexed copies" | Sonnet | **A** | Definitions added. |

## 5. Storage and refresh

| # | Suggestion | Source | Decision | Why / change in v2 |
|---|---|---|---|---|
| 5.1 | Drop-out driven by direct V1 re-verification, not search absence; states `active`, `demarked`, `gone/moved_private_or_deleted`, `renamed`, `unindexed`, `inaccessible` | both | **A** | §6 rewritten; `last_seen_in_search` is diagnostic only; absence counts only when covering `slice_run` rows were complete. |
| 5.2 | Do not commit SQLite or 50k per-repo shards nightly; use Actions cache/release asset, deploy Pages from an artifact, NDJSON/Parquet snapshots, ~500-repo detail shards | both | **A** | §6 and §8 rewritten. |
| 5.3 | `repo_daily` at 50k rows/day is ~18M rows/year: write on change only, or daily for Copilot-authored and weekly for Claude-format | both | **A** | Done. |
| 5.4 | New tables: `blob`, `slice_run`, `edge`, `cluster_override`, `template_blob`, `deny`, `adopter`, `scan_diff`, `repo_state`, `manifest_history`, `plugin_ref`, `schema_version`; unique key on `marker_hit` | both | **A** | Schema updated. |
| 5.5 | sql.js over HTTP range requests as a browser query engine | Sonnet | **R** | Not now; DuckDB-WASM over Parquet (Opus) is noted as the pre-server escalation path if rows exceed ~100k. |
| 5.6 | Permalinks by `databaseId`, redirect map for merged clusters | Sonnet | **A** | Added to §7. |

## 6. UI/UX

| # | Suggestion | Source | Decision | Why / change in v2 |
|---|---|---|---|---|
| 6.1 | Ship a Plugins tab in Phase 3, built from already-parsed marketplace entries | both | **A** | Phase 3 updated; answers open question 2. |
| 6.2 | Cut v1 charts to 3 (Opus) or 4 (Sonnet); charts act as cross-filters; growth chart by `createdAt`, not `first_seen` (which measures the crawler) | both | **M** | Four charts: growth by `createdAt` stacked by native level, stars log histogram, top owners, component/executes-code mix. Plus an "About the data" coverage panel. |
| 6.3 | Install snippets from the manifest's marketplace `name` with the effective path; warn when the name collides with built-in `awesome-copilot` (true for all its forks) | Opus | **A** | Added. |
| 6.4 | Safety: CSV formula-injection neutralisation, CSP, `textContent` only, allow only `https:` URLs, strip bidi controls, cap lengths, `rel="noopener noreferrer nofollow"` | both | **A** | New §7.4. |
| 6.5 | Performance: serialised MiniSearch index built at deploy time, filtering in a Web Worker, columnar dictionary-encoded JSON, debounced chart updates; plain `.json` and rely on Pages transport compression | both | **A** | §7.1 and §8. |
| 6.6 | Extra filters: dual format, executes code, pinned sources, listed by seed marketplaces, referenced-by count, shadowed/misplaced, owner type-ahead, license and topic multi-select, pushed-within chips, diverged-fork toggle, facet counts | both | **A** | §7.2 extended. |
| 6.7 | Trending and adoption sorts once snapshots exist | both | **A** | Phase 4. |
| 6.8 | Card layout on narrow screens; persist column visibility | both | **A** | §7.5. |
| 6.9 | Non-virtualised ARIA grid for screen readers | Sonnet | **M** | Keep virtualisation with `aria-rowcount`/`aria-rowindex`; offer a "plain table" mode for the current page as the accessible fallback. |
| 6.10 | "Report this entry" link opening a prefilled issue that feeds the deny-list; cluster-members export; "open this marker query on GitHub" link | both | **A** | Added. |

## 7. Architecture, risks, open questions, phasing

| # | Suggestion | Source | Decision | Why / change in v2 |
|---|---|---|---|---|
| 7.1 | Phase 0b spike: token test, `path:/` and `-user:` confirmation, exact-filename behaviour, `incomplete_results`, GraphQL batch calibration, fixture capture | both | **A** | Added as Phase 0b (half day); two of its items (`path:/`, `-user:`) are already confirmed. |
| 7.2 | Golden recall set, canaries and scan-failure alerts in Phase 1, not Phase 5 | both | **A** | Moved. Exit criterion includes 100% recall on the golden set. |
| 7.3 | Deny-list in Phase 2; plugin tab in Phase 3; Phase 3 budget 4–5 days | both | **A** | Moved and re-estimated. |
| 7.4 | Rate limiter driven by response headers, GraphQL secondary limits, `concurrency` group in Actions, cursor persistence outside the workspace, scheduled-workflow auto-disable heartbeat | both | **A** | §8 expanded. |
| 7.5 | PAT (or GitHub App installation token) from the start rather than hoping `GITHUB_TOKEN` suffices | Opus | **M** | Fine-grained PAT is the plan; the `GITHUB_TOKEN` test stays in Phase 0b for the record. |
| 7.6 | Classifier fixtures (positive/negative manifests), clustering snapshot tests, `marker_version` column to re-evaluate stored blobs without refetching | both | **A** | §8 testing paragraph. |
| 7.7 | Docs-fingerprint job that alerts when the CLI reference page changes | Sonnet | **A** | Phase 5. |
| 7.8 | New risks: search instability, sort deprecation, non-searchable populations, GraphQL timeouts consuming points, boilerplate over-merge, shadowing, doc inconsistency, PII, hostile JSON, git bloat, workflow auto-disable | both | **A** | §9 rewritten. |
| 7.9 | New open questions: which surface's precedence defines "effective manifest"; how the cloud agent consumes plugins; does VS Code read `.plugin/`; data-retention/PII policy; snapshot cadence; label vs hide Claude-format | Opus | **A** | §10 extended. |
| 7.10 | SSRF: never follow arbitrary `source.url` server-side | Sonnet | **A** | §8 and §9. |

## Reviewer claims I did not adopt as facts

- Opus: "GitHub trimmed PushEvent payloads in 2025" (recalled) — left as unverified; GH Archive remains optional.
- Opus: GraphQL `history(after: "<oid> <n>")` cursor trick — both reviewers flag it as recalled; kept as optional with a Phase 0b test.
- Sonnet: Pages serves `.gz` as opaque — plausible, so v2 ships plain `.json`, but it was not tested.
- Sonnet: "docs say forks must outrank the parent to be indexed" — the observed data contradicts it, so no rule is encoded either way.

## Net effect on the design

The biggest changes from review are (1) verification is now two-stage and head-oid gated because the v1 batch provably times out, (2) refresh and drop-out no longer depend on code search at all, (3) de-duplication unions only on definitive edges with a boilerplate guard and a divergent-fork rule, (4) three large discovery vectors were added (`.claude/settings.json`, README install snippets, root-anchored `path:/` queries), and (5) the tier letters became orthogonal facets with cluster-level union so Copilot-native members are never hidden. The recommendation (Python scanner, SQLite, static site on Pages) is unchanged.
