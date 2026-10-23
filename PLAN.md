# Copilot Plugin Finder: research, plan and spec

Status: **v2, 2026-10-22**, revised after independent reviews by two models (see `reviews/review-opus.md`, `reviews/review-sonnet.md`, decisions in `reviews/SYNTHESIS.md`; the v1 text is kept as `reviews/PLAN-v1-as-reviewed.md`). Sections whose heading carries **(revised v2)** changed materially. All counts come from live probes on 2026-10-22 with the `jj1985` account and are approximate.

## 1. Goal

Build a repeatable process, and then a small tool, that:

1. Finds every public GitHub repository that GitHub Copilot can register as a plugin marketplace or install as a plugin (CLI first; VS Code, Copilot app and cloud agent as far as their rules are documented).
2. Indexes useful metadata about each (repo facts, manifest contents, plugin and skill inventory, which markers matched, who references it).
3. Collapses forks and clones onto one canonical repository without hiding maintained hard forks, keeping copy counts as a signal.
4. Presents the result as a sortable, filterable, graphical static page with direct links to each repo, refreshed on a schedule, with an honest coverage indicator.

Non-goals for v1: private repos, GitHub Enterprise Server, non-GitHub Git hosts (Copilot accepts GitLab marketplaces, but GitHub search cannot see them), skills-only repos installed with `gh skill` or `copilot skill add` (adjacent ecosystem; may become an attribute later), and installing or executing any plugin.

## 2. What marks a repo as a Copilot marketplace or plugin (revised v2)

### 2.1 Definitive rules (from GitHub's own reference)

Sources: [CLI plugin reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference), [Creating a plugin marketplace](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/plugins-marketplace), [Creating a plugin](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/plugins-creating), [Plugins for GitHub Copilot](https://docs.github.com/en/copilot/concepts/agents/about-plugins), [Agent plugins in VS Code](https://code.visualstudio.com/docs/agent-customization/agent-plugins), [Agent Plugins Specification 1.0.0](https://agent-plugins.org/specification).

**Marketplace manifest.** `copilot plugin marketplace add OWNER/REPO` (also `OWNER/REPO#ref`, a Git URL, or a local path; no subpath) succeeds when the repository root contains a `marketplace.json` at one of these paths, checked in this order:

| Order | Path | Notes |
|---|---|---|
| 1 | `marketplace.json` | root; generic filename shared with other ecosystems, so content validation is mandatory |
| 2 | `.plugin/marketplace.json` | rare (24 hits) |
| 3 | `.github/plugin/marketplace.json` | the documented Copilot location |
| 4 | `.claude-plugin/marketplace.json` | Claude Code location; Copilot reads it too |

Required: `name` (kebab-case, max 64; dots allowed for Agent Plugins), `owner {name, email?}`, `plugins[]` with `name` and `source` each. Optional `metadata {description, version, pluginRoot}`; `pluginRoot` prefixes every relative `source`. Entry fields: `description` (≤1024), `version`, `author`, `homepage`, `repository`, `license`, `keywords`, `category`, `tags`, `commands`, `agents`, `skills`, `hooks`, `mcpServers`, `lspServers`, `strict`. `source` is a relative path string, or `{source:"github", repo, ref?, sha?, path?}`, or `{source:"url", ...}`; `sha` must be 40 characters. With `strict:false` the entry itself serves as the plugin manifest, so a plugin directory may legitimately have no `plugin.json`. VS Code additionally accepts npm/PyPI package sources, HTTPS and SCP Git remotes and `file:///` marketplaces.

Because the lookup order is fixed, a root `marketplace.json` or `plugin.json` from an unrelated ecosystem **shadows** a valid `.github/plugin/` or `.claude-plugin/` manifest. The scanner records `effective_manifest_path` (first existing path in CLI order) and `shadowed_manifests[]`; "effective manifest invalid, valid manifest shadowed" is a warning. Whether the CLI falls through after a parse failure is undocumented (open question 9).

**Plugin manifest.** `copilot plugin install OWNER/REPO` or `OWNER/REPO:PATH` succeeds when the plugin directory contains `plugin.json` at one of:

| Format | Path(s) | Required | Distinguisher and components |
|---|---|---|---|
| Agent Plugins 1.0 / 1.1 | `plugin.json` at plugin root only (takes precedence over `.plugin/` and `.claude-plugin/`) | `$schema` **and** `name` | `$schema` is exactly `https://agent-plugins.org/schemas/1.0.0/plugin.schema.json` or `.../1.1.0/...`; other versions are rejected by the CLI. Name: 1–64 chars, lowercase letters, digits, `-`, `.`, alphanumeric at both ends, no `--`/`..`. Permitted fields `$schema,name,version,description,author,homepage,repository,license,keywords,extensions`; unknown fields are reported and ignored (a warning, not a rejection). Skills in `skills/*/SKILL.md`, MCP in `mcp.json`, Copilot-specific parts in `com.github.copilot/{agents,commands,rules,hooks/hooks.json,lsp.json}` |
| Legacy Copilot | `.plugin/plugin.json`, `plugin.json`, `.github/plugin/plugin.json`, `.claude-plugin/plugin.json` (checked in this order) | `name` (kebab-case, letters, digits, hyphens, max 64) | no Agent Plugins `$schema`; optional `description, version, author, homepage, repository, license, keywords, category, tags`; component paths `agents, skills, commands, hooks, extensions, mcpServers, lspServers` with defaults `agents/`, `skills/` (falling back to a root `SKILL.md`), `hooks.json` or `hooks/hooks.json`, `.mcp.json` or `.github/mcp.json`, `lsp.json` |

**Consumer-side configuration** (not a plugin, but names marketplaces): `.github/copilot/settings.json` and `.claude/settings.json` may contain `extraKnownMarketplaces {name: {source: {source:"github", repo, ref?}}}` and `enabledPlugins {"plugin@marketplace": true}`; VS Code also reads `chat.plugins.marketplaces` from `.vscode/settings.json`. Every repo named there is a marketplace by declaration.

**Default and documented marketplaces.** The CLI reference and the finding/installing page say only `github/awesome-copilot` is built in and `github/copilot-plugins` is now opt-in; the older concept page still lists both as defaults. Both are seeds regardless. Also documented as examples: `anthropics/claude-code`, `claudeforge/marketplace`. awesome-copilot's manifest has 183 plugins of which 78 point at ~66 other repos via `source` objects; copilot-plugins has 18 plugins, 16 external across 7 repos. Those referenced repos are plugins by declaration even without a root manifest.

**Surfaces.** Four surfaces consume plugins (CLI, VS Code, Copilot app, cloud agent). Only the CLI's lookup order is documented. v1 of the tool asserts CLI installability and records `surfaces[]` as `{cli: docs, vscode: unknown, app: unknown, cloud_agent: unknown}` until the rules are confirmed (open question 8).

### 2.2 Markers, measured

Hit counts are files, not repos; default results exclude forks; `filename:` is **fuzzy** (it matched `umbraco-marketplace.json`, `kimi-marketplace.json`, `.agent-marketplace.json`), and `path:DIR` matches every subdirectory beneath `DIR`, so every hit is filtered client-side on exact basename and exact path before it counts (section 3.4). `path:/` anchors to the repository root and is preferred.

| ID | Marker (code-search query) | Hits (2026-10-22) | Reliability | Meaning |
|---|---|---|---|---|
| M-GH | `path:/.github/plugin filename:marketplace.json` | 888 (+419 with `fork:only`) | definitive at root | Copilot-native marketplace |
| M-PL | `path:/.plugin filename:marketplace.json` | 24 | definitive at root | legacy location (`OpenHands/extensions`, `Azure/azure-functions-skills`) |
| M-ROOT | `path:/ filename:marketplace.json plugins owner` | 399, all root-level | definitive after JSON validation | root marketplace (`microsoft/work-iq`, `microsoft/power-platform-skills`, ...) |
| M-CL | `path:/.claude-plugin filename:marketplace.json` | ~43,900 | definitive for installability, Claude-authored | Copilot-installable (Claude format) marketplace |
| M-GHS | `path:.github/plugins filename:marketplace.json` | 24 | false positive (wrong directory name); keep as "misplaced manifest" flag | not registrable |
| P-AP | `path:/ filename:plugin.json agent-plugins.org` | ~2,450 root-level (≈10,560 unanchored, mostly plugins inside marketplaces) | definitive (Agent Plugins format) | Agent Plugins plugin repo |
| P-GH | `path:/.github/plugin filename:plugin.json` | 291 | definitive (legacy) | legacy Copilot plugin repo |
| P-GH-ext | `path:.github/plugin filename:plugin.json extensions` | 13 | definitive Copilot-specific | legacy plugin with SDK extensions |
| P-PL | `path:/.plugin filename:plugin.json` | 193 | definitive (legacy location 1; `vercel/vercel-plugin`) | legacy plugin repo |
| P-CL | `path:/.claude-plugin filename:plugin.json` | ~32,200 | definitive for installability, Claude-authored | Copilot-installable (Claude format) plugin |
| P-ROOT | `path:/ filename:plugin.json` + one content term per slice (`skills`, `agents`, `hooks`, `mcpServers`, `commands`) | untested | heuristic until the sibling check passes (`skills/`, `agents/`, `hooks.json`, `.mcp.json`, `com.github.copilot/`, root `SKILL.md`, or a component-path field) | legacy plugin at root |
| S-COP | `path:com.github.copilot` | 515 files | definitive Copilot-specific signal | strengthens P-AP |
| S-COPX | `filename:plugin.json "com.github.copilot"` | 164 | definitive Copilot-specific signal | strengthens P-AP |
| S-SET | `path:.github/copilot filename:settings.json extraKnownMarketplaces` (`enabledPlugins`: 119) | 102 | definitive pointer (consumer side) | discovery vector + adopter |
| S-SET-CL | `path:.claude filename:settings.json extraKnownMarketplaces` | 4,104 | definitive pointer; VS Code reads it | discovery vector + adopter |
| S-VSC | `path:.vscode filename:settings.json "chat.plugins.marketplaces"` | 19 | pointer | discovery vector |
| S-README | `"copilot plugin marketplace add" extension:md` (also `"copilot plugin install"`, `"/plugin marketplace add"`) | 4,632 | text pointer; extract `owner/repo` tokens from text-match fragments | largest secondary vector; finds non-default-branch marketplaces too |
| R-README | repository search `"plugin marketplace add" in:readme created:>DATE` / `pushed:>DATE` | untested | date-filterable | incremental discovery |
| S-HOOK | `path:.github/hooks filename:hooks.json` | 619 | repo-level Copilot hooks, not a plugin | ignore for inclusion |
| X-CUR / X-CODEX | `path:.cursor-plugin filename:marketplace.json` (2,228); `path:.agents/plugins filename:marketplace.json` (~8,000) | — | Cursor / Codex formats, not read by Copilot | co-occurrence attributes only |
| T-* | topics `copilot-plugin` 50, `copilot-plugins`, `copilot-marketplace` 1, `agent-plugins` 368, `claude-code-plugin` 11,553, `claude-code-marketplace` 549 | — | heuristic; never sufficient alone | discovery + attribute |

Nested hits are real: `jj1985/worktools` has `soar-toolkit/.github/plugin/marketplace.json`; `microsoft/aspire-skills` keeps manifests under `.github/plugins/aspire-skills/.claude-plugin/`. They are not registrable marketplaces (but may be installable via `owner/repo:path`), so they are stored with `evidence=verified-nested` and a "misplaced manifest" flag, never silently dropped.

### 2.3 Facets instead of tiers (revised v2)

Inclusion is described by orthogonal, stored facets; the old tier letters survive only as named default filters.

| Facet | Values | Derived from |
|---|---|---|
| `kind` | marketplace, plugin, both | which effective manifests exist |
| `native_level` | copilot-authored (any of `.github/plugin/`, `.plugin/`, root Agent Plugins manifest, `com.github.copilot/`, `extensions`), copilot-installable-claude-format (only `.claude-plugin/` files), declared-only | marker set |
| `evidence` | verified-root, verified-nested, declared-only | verification result |
| `format` | agent-plugins-1.0, agent-plugins-1.1, legacy, claude | manifest content |
| `dual_format` | bool | both `.github/plugin/` and `.claude-plugin/` present (the user's own repos) |
| `copilot_specific` | bool | `com.github.copilot/`, `extensions`, hooks or LSP config present |
| `executes_code` | set of {hooks, mcp-stdio, mcp-remote, lsp, extensions, scripts} | blobs and tree listing |
| `surfaces[]` | per-surface docs/observed/unknown | section 2.1 |

Default view: `native_level = copilot-authored` and `evidence = verified-root`, with a visible chip "Claude-format hidden (N)". Cluster-level facets are the **union over members**, so a cluster whose canonical is Claude-format but has a Copilot-authored member is still shown (reviewer finding). Expected sizes: Copilot-authored ≈ 1,500–3,000 repos; Claude-format ≈ 45k+; declared-only: hundreds.

## 3. Discovery strategy (revised v2)

### 3.1 Search surfaces and their limits (verified unless marked)

| Surface | Use | Limits |
|---|---|---|
| REST `GET /search/code` | primary discovery by path/filename/content | 1,000 results per query (page 11 → HTTP 422); 10 req/min for this token though authenticated; `per_page` ≤ 100; default branch only; files < 384 KB; archived repos, repos with no activity for about a year and repos with ≥500k files are not indexed (docs); forks excluded unless `fork:only` (`fork:true` behaved identically: 419); date qualifiers silently ignored (`pushed:>…` → 0); at least one search term required besides `filename:`; `filename:` fuzzy; `path:/` anchors to root; negative `-user:`/`-org:` works (888 → 848 when excluding `microsoft`, which has 28); `sort=indexed` is documented "closing down" so it is best-effort only; totals are estimates (three disjoint `size:` buckets summed to 49,232 against a reported 43,904); `incomplete_results:true` with `total_count:0` was observed once during review and must trigger a retry |
| REST `GET /search/repositories` | topics, `in:readme`, with `created:`/`pushed:`/`stars:` partitioning | examines up to 4,000 matches, retrievable 1,000; 30 req/min |
| GraphQL `search` | repositories only (SearchType: ISSUE*, REPOSITORY, USER, DISCUSSION; no CODE) | 1,000 cap |
| GraphQL `repository`/`nodes(ids:)` | verification and refresh (section 3.4) | points are not the constraint; a ~10 s execution timeout is: 25/50/100 repos × 8 blob lookups returned HTTP 502 and still consumed points; 50 repos with root tree only ≈ 5.4 s; 10 repos with 8 blobs with text ≈ 5.3 s |
| REST contents / git trees / `raw.githubusercontent.com/<owner>/<repo>/<sha>/<path>` | recursive trees; points-free immutable blob fetch (IP rate-limited) | 5,000 req/h core |
| Sourcegraph public stream API | optional free diagnostic only | indexed 83 of 888 `.github/plugin/marketplace.json` files |
| GH Archive / BigQuery | optional: `CreateEvent`/`ForkEvent` name heuristics as cheap candidates | no file paths in events; costs money; PushEvent payload changes unverified |
| Existing catalogs | seeds and recall: awesome-copilot plugin directory, copilot-plugins, agenticskills.io, `louis030195/awesome-agent-plugins`, `ilderaj/agent-plugin-marketplace` | curated, lag behind |

Index lag measured: `jj1985/plextrac-skills` (created 2026-10-20) was searchable by 2026-10-22; `jj1985/skills` (0-star fork from 2026-10-21) is not, even with `fork:true`. Code search sees 419 of awesome-copilot's 5,191 forks (8%); **search is never a fork census**; `forkCount` is.

### 3.2 Query plan and budget

1. Every marker in 2.2 is a query family in `markers.yaml` (query, slice axes, expected path regex, exact basename, min/max size).
2. Slices over ~900 hits are split by `size:` buckets first (manifests cluster between 300 B and 3 KB), then by content terms (`"$schema"`, `strict`, `mcpServers`, `keywords`, `category`) because same-template manifests share one byte size, then by `-user:`/`-org:` carve-outs of the largest owners. A slice is complete only when its last page is short and `incomplete_results` was false; this is persisted per `(query, slice)` in `slice_run`.
3. Forks: repeat each family with `fork:only`.
4. Budget (corrected from v1): Copilot-authored families ≈ 30–60 requests (minutes). A full Claude-format sweep ≈ 45 slices × 10 pages = 450 requests ≈ 45 min ideal, ≈ 1,000 requests ≈ 1.7 h with bisection and retries. Cadence: Copilot-authored nightly; Claude-format full sweep every 2–3 nights; `sort=indexed` first pages opportunistically with a health check that notices when order stops changing.
5. Date-filtered repository searches (`R-README`, topics, `created:>yesterday`) run nightly as the cheap incremental vector.

### 3.3 Secondary discovery (graph expansion)

For every verified marketplace manifest, enqueue each external `source.repo` (normalised: shorthand, full URL, `.git` suffix, case) and record a `plugin_ref` row. For every settings file (S-SET, S-SET-CL, S-VSC), enqueue each marketplace repo and record an `adopter` row. For S-README, use the `application/vnd.github.text-match+json` media type to pull `owner/repo` tokens from fragments without fetching files. For each plugin manifest, enqueue `repository`/`homepage` when they name another GitHub repo (as a provenance link only). Repeat until the frontier is empty. Non-GitHub URL/npm/PyPI sources are stored as `source_kind` + `source_host` ("external, not indexed"), not as failures.

### 3.4 Verification: two-stage, head-oid gated (revised v2)

0. **Hit filter.** Exact basename and exact path check against the marker's regex; non-matching hits are discarded before any API spend. Store `(repo id, node id, path, blob sha, fork flag)` from the search response itself; identical blob shas across repos are already a free duplicate signal.
1. **V1 gate** (~50 repos per query, ≈5 s, adaptive): `id`, `databaseId`, `nameWithOwner`, `isFork`, `parent{nameWithOwner}`, `templateRepository{nameWithOwner}`, `isArchived`, `archivedAt`, `isEmpty`, `isLocked`, `isMirror`, `isTemplate`, `stargazerCount`, `forkCount`, `createdAt`, `pushedAt`, `defaultBranchRef{name target{oid committedDate tree{oid entries{name type oid}}}}`, plus owner type, license, language, topics, latest release. If the head oid equals the stored one, stop for that repo. Root entries reveal which manifest directories and README exist and their oids.
2. **V2 fetch** (10–20 repos per query, only for new or changed repos): look up only the directories that exist (`HEAD:.github/plugin`, `HEAD:.claude-plugin`, `HEAD:.plugin`, root files) and fetch blob `text` only for oids not already in the content-addressed `blob` table. Parse JSON, validate, compute `effective_manifest_path`, `shadowed_manifests[]`, facets.
3. Batch size halves on 502/timeout and grows slowly on success; 2–3 queries in flight at most; exponential backoff with jitter on 403 secondary limits, 429, 502/504.

A record is admitted with `evidence=verified-root` only if the effective manifest exists at the exact root path and parses with the required fields; otherwise `verified-nested` or `declared-only`.

### 3.5 Refresh is separate from discovery (new in v2)

Known repos are refreshed by V1 directly (via `nodes(ids:)`, rename- and transfer-proof), never by whether search still returns them: Copilot-authored nightly, Claude-format every 3–7 days split across nights (~30k gated V1 checks per hour serially). Search presence is logged as `last_seen_in_search` for diagnostics only.

### 3.6 Completeness checks (revised v2)

- **Golden recall set** asserted every run: the ~66 awesome-copilot external repos, the 7 copilot-plugins external repos, the documented example marketplaces, the user's own repos, and the settings-file pointers. A miss fails the scan loudly.
- **Coverage estimate**: capture–recapture between code search (capture A) and the pointer vectors (manifest `source` graph, settings files, README snippets; capture B) over verified true positives. Shown in the UI header with the caveat that both captures over-sample popular repos, so it is indicative, not a true population estimate.
- **Regression guard**: fail if the verified row count drops >10% versus the previous scan or if any slice regresses by more than N% without `incomplete_results` being set.
- Sourcegraph: optional diagnostic only.

## 4. Metadata to collect (revised v2)

### 4.1 Cheap (V1 + V2, no extra calls)

Repository: `databaseId` (primary key), node `id`, `nameWithOwner`, `url`, `description`, `owner.login`, `owner.__typename`, `owner.databaseId` (for avatar URLs, no image storage), `isFork`, `parent`, `templateRepository`, `isArchived`, `archivedAt`, `isTemplate`, `isMirror`, `isEmpty`, `isLocked`, `stargazerCount`, `forkCount` (direct forks; label as such), `createdAt`, `pushedAt`, head commit `committedDate` (better "last updated" than `pushedAt`), `homepageUrl`, `licenseInfo.spdxId`, `primaryLanguage`, topics, `latestRelease`, default branch name, head oid, root tree oid, root entry names and oids, README filename and oid (any case/extension, chosen from the tree), manifest blobs by oid.

Derived: `effective_manifest_path`, `shadowed_manifests[]`, facets (2.3), `marketplace{name, owner_name, description, version, pluginRoot}`, declared plugins (`name, version, description, source_kind, source_host, source_repo, source_path, ref, sha, pinned, keywords, category, tags, strict`), `plugin_count`, `external_plugin_count`, `has_license`, `markers_matched[]`, `schema_valid`, `schema_warnings[]` (name constraints, lengths, 40-char `sha`, unknown fields), `referenced_by_marketplaces`, `referenced_by_settings`, `listed_by_seed` (awesome-copilot / copilot-plugins), `executes_code` set.

### 4.2 Expensive (prioritised by facets and stars)

- Per-plugin inventory built **from marketplace entries first** (a missing `plugin.json` is normal when `strict:false` or for inline entries), resolving `source` against `pluginRoot`. For each local plugin: directory tree oid (plugin-level de-dup key), then two-level tree listing to count skills (`skills/*/SKILL.md` or root `SKILL.md`), agents, commands, hooks, MCP servers (and transport/command presence), LSP, extensions, scripts. Repos with >20 plugins use one REST recursive tree call.
- SKILL.md frontmatter (`name`, `description`) and blob oid: Copilot-authored repos and starred Claude-format repos only.
- README excerpt: ~300 characters, markdown stripped, text only; Copilot-authored and starred repos.
- `history.totalCount` and `last_commit_touching_manifest`: canonical Copilot-authored repos only.
- JSON-schema validation against the published Agent Plugins schemas, cached per blob oid, re-run when `marker_version` changes.

Dropped from v1: emails (never leave SQLite), `watchers`, `diskUsage`, `isDisabled` as a display field, `updatedAt` as a signal, per-skill rows for unstarred Claude-format repos.

### 4.3 Record schema (logical, revised v2)

```
repo            id (databaseId) PK, node_id, full_name, owner, owner_type, owner_id, description, homepage,
                stars, forks, created_at, pushed_at, committed_at, archived_at, is_fork, parent_id, template_repo_id,
                is_archived, is_template, is_mirror, is_empty, default_branch, license, language, latest_release, latest_release_at,
                head_oid, root_tree_oid, readme_name, readme_oid, readme_excerpt,
                kind, native_level, evidence, format, dual_format, copilot_specific, executes_code (json), surfaces (json),
                effective_manifest_path, shadowed_manifests (json), misplaced_manifest,
                marketplace_name, marketplace_owner_name, marketplace_description, marketplace_version, plugin_root,
                plugin_count, external_plugin_count, skill_count, agent_count, hook_count, mcp_count, lsp_count, extension_count,
                schema_valid, schema_warnings (json), referenced_by_marketplaces, referenced_by_settings, listed_by_seed,
                cluster_id, is_canonical, network_size, indexed_copies, diverged_fork,
                status, first_seen, last_verified, last_seen_in_search, missing_since, marker_version
repo_topic      repo_id, topic
repo_state      repo_id, head_oid, root_tree_oid, verified_at, etag
blob            oid PK, byte_size, text, parsed_json, parse_error, owner_count, is_template_blob, first_seen
manifest_history repo_id, path, blob_oid, first_seen, last_seen
marker_hit      repo_id, marker_id, path, blob_oid, is_root, first_seen, last_seen   UNIQUE(repo_id, marker_id, path)
plugin          id, repo_id, name, version, description, source_kind, source_host, source_repo_id, source_path, ref, sha, pinned,
                keywords (json), category, tags (json), strict, format, dir_tree_oid, skill_count, agent_count, hook_count, mcp_count, executes_code (json)
plugin_ref      marketplace_repo_id, entry_name, target_repo_id, target_path, ref, sha      (distribution edges; one plugin, many distributors)
skill           plugin_id, name, description, path, blob_oid
adopter         repo_id, marketplace_ref, file_path, enabled_plugins (json)
edge            repo_a, repo_b, signal, evidence (json), created_at                 (de-dup evidence; definitive vs strong vs medium)
cluster_override action (merge|split), repo_ids (json), reason, created_at         (mirrors cluster_overrides.yaml)
template_blob   oid, owner_count, reason
deny            repo_id | owner, reason, created_at
slice_run       scan_id, query, slice, pages_fetched, last_page_short, incomplete_results, total_count, completed_at
scan            id, started, finished, status, requests_used (json by resource), repos_seen, repos_verified, errors, recall_golden, coverage_estimate
scan_diff       scan_id, repo_id, change (new|changed|demarked|gone|renamed|merged|split)
repo_snapshot   repo_id, date, stars, forks                                        (daily for copilot-authored, weekly for claude-format, or on change)
schema_version  version, applied_at
```

## 5. De-duplication rules (revised v2)

### 5.1 Signals, cheapest first

| # | Signal | Class | Guard |
|---|---|---|---|
| 1 | `isFork` + `parent` | definitive edge (provenance) | subject to the divergence test below |
| 2 | `templateRepository` | definitive edge (template family) | descendants are a family, not clones of each other |
| 3 | identical `root_tree_oid` | definitive clone | root tree must contain a manifest blob and ≥3 entries (near-empty trees are boilerplate) |
| 4 | identical plugin directory tree oid | strong (plugin-level) | none; byte-identical vendored plugin |
| 5 | identical manifest blob oid | strong | not a `template_blob` (oid in >3 unrelated owners or <300 bytes) |
| 6 | identical README blob oid | strong | same boilerplate guard |
| 7 | identical SKILL.md blob oid sets | medium (plugin-level) | fraction ≥0.8 of the smaller side |
| 8 | manifest identity (`marketplace.name` + owner + sorted plugin names; or plugin `name`+`version`+`description`) | medium | requires plugin count ≥2 or non-trivial name entropy; never for `my-plugin`, `example`, `1.0.0`-style values alone |
| 9 | structural fingerprint (sorted plugin/skill/agent names) | medium | as 8 |
| 10 | first-commit oid equality | strong | computed only for repos already linked by a medium signal (GraphQL history-cursor trick is unverified; REST fallback) |
| 11 | manifest `repository`/`homepage` pointing at another indexed repo | provenance link only | never cluster-forming |

Distribution is not duplication: a marketplace listing a repo as a `source` creates a `plugin_ref`, never an `edge`.

### 5.2 Clustering

Union-find runs only on definitive edges (1 after the divergence test, 2 within a family, 3). Strong and medium signals create `edge` rows with evidence; a repo joins a cluster on non-definitive evidence only when two independent strong signals (4–6, 10) agree, or one strong signal links it to the cluster's canonical and no `template_blob` is involved. Everything else stays a `similar_to` link shown in the detail panel. Alarms fire when a cluster exceeds 50 members or its canonical changes between scans. `cluster_overrides.yaml` records manual merges and splits that survive rescans.

**Divergence test for forks.** A fork is collapsed under its parent only if its effective manifest oid equals the parent's or it has no commits after creation. It becomes its own record (`diverged_fork=true`, "fork of Y" shown, not counted in the parent's copies) when the manifest oid differs **and** any of: own stars ≥ 5, marketplace `name` differs, it is listed by a seed marketplace, or the parent is archived/gone.

Plugin-level clusters (signals 4, 7, 8) are computed separately and drive the Plugins view; repo clusters do not depend on them.

### 5.3 Canonical choice (tie-breakers, in order)

0. Active (not archived, not gone, not demarked) with a valid effective manifest, preferring `evidence=verified-root`.
1. The fork-network root (walk `parent` up to three levels in GraphQL, or one REST call for `source` per cluster root).
2. The repo a seed marketplace points at (GitHub's own judgement of the maintained copy).
3. The repo named by the manifest's own `repository`/`homepage` field, if it contains the same manifest name.
4. Oldest `createdAt`.
5. Most stars; then organisation over user; then alphabetical.

Displayed counts: `network_size = max(forkCount, indexed fork members)` and `indexed_copies` (non-fork cluster members found in search), defined so nothing is double counted. Non-canonical members remain in the database with `is_canonical=false`.

### 5.4 Validation

Phase 2 deliverable: a stratified audit of 100 clusters (by size and by forming signal) with per-signal precision, used to decide which signals may union. Clustering has snapshot tests on a frozen sample.

## 6. Storage and refresh (revised v2)

- **Store:** SQLite (`index.sqlite`) with the tables in 4.3, kept in the GitHub Actions cache between runs and uploaded as a release asset weekly; never committed nightly. Git holds only `scan_diff` NDJSON and small logs. The site is deployed to Pages from a build artifact, not from committed files.
- **Blob cache:** content-addressed by git blob oid; a blob is fetched once ever. This is what makes 5,191 awesome-copilot forks cheap.
- **Exports for the site:** `repos.json` (columnar, dictionary-encoded owner/language/license, plain JSON relying on Pages transport compression) for the default view; `repos-claude.json` loaded on toggle; detail shards of ~500 repos (`detail-0001.json`, keyed by `id // 500`); a serialised MiniSearch index built at deploy time; `plugins.json`.
- **Identity:** `databaseId` is the key; permalinks use it; a redirect map handles merged clusters and renames.
- **Snapshots:** `repo_snapshot` daily for Copilot-authored, weekly for Claude-format, written only when stars or forks changed.
- **Status machine** (driven by V1 re-verification, never by search absence): `active` → `demarked` (effective manifest gone at HEAD) → may return to `active`; `active` → `gone` (node null / NOT_FOUND; GitHub does not distinguish deleted from made-private, so the label is "unavailable"); `renamed` when `nameWithOwner` changes for the same id; `unindexed` when verified present but absent from search (archived, inactive, huge; expected per docs); `inaccessible` for disabled or DMCA. Absence from search only matters for diagnostics and only when the covering `slice_run` rows were complete, so one rate-limit incident cannot mark hundreds of repos missing. Nothing is deleted.
- **Schedule:** nightly: Copilot-authored discovery sweep, date-filtered repo searches, graph expansion, V1 refresh of Copilot-authored repos, export and deploy. Every 2–3 nights: Claude-format full sweep. Rolling 3–7 nights: Claude-format V1 refresh. Weekly: release-asset upload, docs-fingerprint check. Each run writes `scan` with golden-set recall and coverage estimate and fails loudly on regression.

## 7. UI/UX (revised v2)

### 7.1 Delivery options compared

| | Static site (recommended) | Small server app |
|---|---|---|
| Shape | SPA built from exported JSON; GitHub Pages; scanner in Actions | FastAPI + SQLite, server-side filtering, HTMX or React |
| Scale | 2–3k default rows trivially; ~50k Claude-format rows behind a toggle with columnar JSON, a Web Worker for filter/sort/search and a virtualised table | unlimited |
| Ops | none; free | host, uptime, token handling |
| Search | serialised MiniSearch index over name, description, topics, plugin names (skills for Copilot-authored) | SQLite FTS5 |
| Escalation path | DuckDB-WASM over Parquet with HTTP range requests (still static) if rows pass ~100k or plugin/skill rows reach hundreds of thousands | — |

Recommendation: static site. A server becomes worth it only for accounts, alerts or "report false positive" workflows beyond a prefilled-issue link; none is in scope.

### 7.2 Features

- Tabs: **Repositories** (default) and **Plugins** (from marketplace entries, with distributors and source repo); Skills tab in phase 4.
- Table (TanStack Table + Virtual): full name (link), owner, native-level badge, kind, format, stars, network size, copies, plugins, skills, executes-code badges, language, license, created, last commit, last verified, flags (archived, template, misplaced/shadowed manifest, warnings, diverged fork). Column visibility persisted; card layout under ~640 px.
- Filters with facet counts: text search; plugin-name and skill-name search; stars range; owner type and owner type-ahead; language, license and topic multi-select; archived; template; network-size and copies ranges; `kind`, `native_level`, `evidence`, `format`, `dual_format`, `copilot_specific`, `executes_code`; listed by seed marketplace; referenced-by count; pinned sources only; has external plugins; created and last-commit date ranges with "pushed within 30/90/365 days" chips; "new this week"; "show non-canonical copies"; "show diverged forks"; "verified in last N days"; valid / with warnings.
- Sorts on every column, multi-sort; default stars desc with clusters collapsed; "trending" (7-day star delta) and "adoption" (reverse references) once snapshots exist. Filter and sort state live in a versioned URL hash.
- Charts (four in v1, all acting as cross-filters on the same row set, debounced, using precomputed bins): growth by `createdAt` per week stacked by native level (not `first_seen`, which measures the crawler); stars log histogram; top 20 owners; component and executes-code mix. Later: format split over time, cluster-size concentration.
- "About the data" panel: last scan time and status, repos verified, requests used, golden-set recall, coverage estimate with its caveat, incomplete slices, the fork-indexing caveat, and a link to the scan log.
- Detail panel: description, README excerpt (text only), marketplace metadata, why it was included (markers with blob links `https://github.com/<repo>/blob/<sha>/<path>`), effective and shadowed manifests, plugin list with per-plugin components and distributors ("listed in"), skills, executes-code section listing hook events and MCP commands as text, validation result, cluster members and the evidence edges that formed them, "fork of / generated from" line, install snippets built from the manifest's marketplace `name` and the effective path (`copilot plugin marketplace add owner/repo[#ref]` only for `verified-root` marketplaces; `copilot plugin install owner/repo:path` for nested; `plugin@marketplace` for entries; a warning when the name collides with the built-in `awesome-copilot`, which is true for all its forks), copy buttons, "open this marker query on GitHub", "report this entry" (prefilled issue feeding `deny`), and "what changed since last scan".
- Exports: CSV and JSON of the current view including filter state, scan id and generation time; cluster-members export.

### 7.3 Accessibility

Keyboard navigation, visible focus, colour never the sole encoding, `aria-rowcount`/`aria-rowindex` on the virtualised grid plus a "plain table" mode for the current page as the screen-reader fallback.

### 7.4 Safety (new in v2)

All third-party strings rendered with `textContent`; no README markdown rendering; CSP meta tag (no inline scripts, images only from `avatars.githubusercontent.com`); outbound links `rel="noopener noreferrer nofollow"` and only `https:` URLs; bidi control characters stripped; string lengths capped; CSV cells starting with `=`, `+`, `-`, `@` prefixed to neutralise formula injection; no emails in any export.

## 8. Architecture and tech choices (revised v2)

- Scanner: Python 3.12 (`PYTHONUTF8=1`), `httpx`, `sqlite3`, `jsonschema`, `pyyaml`. Rate limiting driven by response headers (`x-ratelimit-remaining/reset`, `retry-after`) per resource, GraphQL secondary-limit awareness, adaptive GraphQL batch size, at most 2–3 concurrent queries, exponential backoff with jitter; `incomplete_results` is a retry. Cursor state per `(query, slice, page)` persisted in SQLite so an interrupted run resumes. Never clones or executes anything; never follows non-GitHub `source.url` server-side.
- CLI: `cpf discover | expand | verify | enrich | dedup | export | scan | stats | diff`.
- Auth: fine-grained PAT (public read) as an Actions secret; the `GITHUB_TOKEN` question is tested once in Phase 0b for the record. One token means local runs share the Action's budgets; documented.
- Runner: GitHub Actions nightly cron with `concurrency` group, job time limits under the 6-hour cap, SQLite restored from cache, artifacts uploaded, Pages deployed from artifact, a heartbeat commit so scheduled workflows are not auto-disabled after 60 idle days, failure alerts on golden-set miss or row-count regression.
- Front end: Vite + TypeScript, TanStack Table/Virtual, Observable Plot or Chart.js, MiniSearch in a Web Worker.
- Data-driven rules: `markers.yaml` (queries, path regexes, slice axes) and `marker_version` stored per record so rule changes re-evaluate cached blobs without refetching; `cluster_overrides.yaml`; `deny.yaml`.
- Testing: classifier fixtures (valid, invalid, shadowed, nested, suffix-matched filenames like `umbraco-marketplace.json`, `.github/plugins` typo, Obsidian/Jenkins `plugin.json`), golden recall set, clustering snapshot tests on a frozen sample.
- Repo layout: `scanner/`, `site/`, `rules/` (markers, overrides, deny), `docs/PLAN.md`, `.github/workflows/scan.yml`.

## 9. Risks and limits (revised v2)

- Search backend: approximate and overlapping counts, `incomplete_results`, regressing totals, `sort=indexed` deprecation, fuzzy `filename:`, 1,000 cap, 10 req/min.
- Non-searchable populations by design: archived, inactive >1 year, huge repos, most zero-star forks, non-default branches; covered partly by graph expansion and direct re-verification, otherwise listed as `unindexed`.
- GraphQL: ~10 s execution timeout; timeouts consume points; secondary limits on bursts.
- False positives: nested or misplaced manifests, shadowed manifests, test fixtures and tutorials, template repos and their copies, generic `plugin.json`/`marketplace.json` from other ecosystems, suffix-matched filenames.
- False negatives: root manifests with unusual content, `owner/repo#ref` marketplaces on non-default branches, plugins reachable only via `owner/repo:path`, GitLab/other hosts, private repos.
- De-dup: boilerplate blobs over-merge without the guard; transitive chaining; maintained hard forks hidden without the divergence test; under-merge of renamed vendored copies without plugin-dir oids.
- Scale asymmetry: Claude-format is 15–30× the Copilot-authored population; keep it behind a toggle and on a slower cadence.
- Storage/ops: git bloat if data is committed; `repo_snapshot` growth; scheduled-workflow auto-disable; one shared token budget.
- Content hazards: huge or deeply nested JSON, bidi characters, `javascript:` URLs, formula injection; PII (emails) in manifests; takedown path needed (`deny` + report link).
- Moving target: Agent Plugins 1.1 recognition, default-marketplace changes and doc contradictions appeared within weeks; `markers.yaml` and the docs-fingerprint job absorb this.

## 10. Open questions (revised v2)

1. Claude-format cadence: full sweep every 2–3 nights as planned, or nightly once the pipeline is proven cheap?
2. Hosting: GitHub Pages under `jj1985` with Actions, or local-only runs with a static file opened from disk?
3. Token: does the Actions `GITHUB_TOKEN` work for `search/code` (tested in Phase 0b)? PAT assumed either way.
4. Adopters dataset: shown as a secondary table gated by a star threshold (recommended), or only as a counter on each marketplace?
5. Cursor/Codex co-occurrence flags and npm/PyPI source kinds: keep as free attributes (recommended) or drop?
6. Medium-signal clustering aggressiveness, decided after the Phase 2 audit.
7. Should Claude-format repos be labelled "Copilot-installable (Claude format)" in the default view's hidden-count chip, or hidden entirely until toggled?
8. Per-surface rules: how do VS Code, the Copilot app and the cloud agent pick the effective manifest, and does VS Code read `.plugin/` ("legacy OpenPlugin")?
9. Does the CLI fall through to the next manifest path when the first existing one fails to parse?
10. Data retention and PII policy (emails never exported; how long to keep `gone` rows and snapshots).

## 11. Phased implementation plan (revised v2)

- **Phase 0 (done):** marker census, cap/rate-limit/fork/negation/`path:/` verification, GraphQL cost and timeout behaviour (measured by review), seed manifest analysis.
- **Phase 0b, spike (half day):** `GITHUB_TOKEN` test; text-match media type for S-README; GraphQL batch calibration (10/25/50 repos, tree-only vs blobs); `incomplete_results` handling; history-cursor trick; fixture capture for the classifier; confirm `.gz` vs plain JSON on Pages.
- **Phase 1, crawler core (3 days):** `markers.yaml`, discovery with size/term/owner partitioning, exact-path hit filter, `slice_run` and resumable cursors, two-stage verification with blob cache, SQLite schema with migrations, golden recall set, scan summary and failure alerts, `cpf stats`. Exit: Copilot-authored population enumerated with parsed manifests, 100% golden-set recall, nightly run under 30 minutes.
- **Phase 2, expansion and de-dup (2–3 days):** graph expansion (manifest sources, settings files, README snippets), `plugin_ref`/`adopter` tables, reverse-reference counts, clustering with definitive edges plus boilerplate guard and divergence test, canonical selection, deny-list, overrides file, 100-cluster audit with per-signal precision.
- **Phase 3, static UI (4–5 days):** exports, Repositories and Plugins tabs, filters with facet counts, four cross-filtering charts, detail panel with install snippets and evidence, About-the-data panel, CSV/JSON export, safety measures, URL state, Pages deploy from artifact.
- **Phase 4, Claude-format at scale and enrichment (3–5 days, mostly machine time):** partitioned sweeps on the 2–3 night cadence, rolling V1 refresh, per-plugin inventory and skills for Copilot-authored and starred repos, schema validation, snapshots with trending and adoption sorts, Skills tab.
- **Phase 5, hardening:** coverage estimate in the header, docs-fingerprint job, optional GH Archive candidate feed, `cpf diff` reports, documentation, DuckDB-WASM evaluation if row counts demand it.

## Appendix A. Probe log (2026-10-22)

- `gh api rate_limit`: `code_search` 10/min, `search` 30/min, `core` 5000/h, `graphql` 5000 points/h (authenticated as jj1985).
- `search/code` page 11 at `per_page=100`: HTTP 422 "Cannot access beyond the first 1000 results".
- `path:.github/plugin filename:marketplace.json`: 884; `path:/.github/plugin ...`: 888; first 100 results contain 0 forks; `fork:true` and `fork:only` both 419 (all forks); `-user:microsoft` and `-org:microsoft`: 848 (microsoft org alone: 28).
- `path:.claude-plugin filename:marketplace.json`: 43,904; `size:<600` 25,024; `size:600..1200` 15,712; `size:>1200` 8,496; `pushed:>2026-10-01` 0 (qualifier unsupported).
- `path:.plugin filename:marketplace.json`: 24; `path:.plugin filename:plugin.json`: 193; `path:.claude-plugin filename:plugin.json`: 32,192.
- `filename:marketplace.json path:/`: 1,580 with basenames including `kimi-marketplace.json` (1) and `umbraco-marketplace.json` (3) on page 1; `path:/ filename:marketplace.json plugins owner`: 399 (reviewer); `path:/ filename:plugin.json agent-plugins.org`: 2,456 (unanchored 10,560).
- `filename:marketplace.json "plugins" "owner"` excluding `.claude-plugin/.github/.cursor-plugin/.plugin` paths: 8,320, dominated by `.agents/plugins/marketplace.json` (Codex CLI).
- Reviewer-verified vectors: `path:.claude filename:settings.json extraKnownMarketplaces` 4,104; `"copilot plugin marketplace add" extension:md` 4,632; `path:.vscode filename:settings.json "chat.plugins.marketplaces"` 19; `github/awesome-copilot` `forks_count` 5,191.
- `user:jj1985 filename:marketplace.json`: 5 files across 3 repos, including nested `soar-toolkit/.github/plugin/marketplace.json` in `jj1985/worktools`.
- `repo:jj1985/skills filename:plugin.json fork:true`: 0 (unindexed fork); `repo:jj1985/plextrac-skills filename:marketplace.json`: 2 (indexed within two days of creation).
- GraphQL `SearchType` enum: ISSUE, ISSUE_ADVANCED, ISSUE_SEMANTIC, ISSUE_HYBRID, REPOSITORY, USER, DISCUSSION. `Repository.templateRepository`, `archivedAt`, `isEmpty`, `isLocked` exist (reviewer introspection).
- GraphQL batch of two repositories with 7 `object()` lookups each: cost 1. Reviewer measurements: 25/50/100 repos × 8 blob lookups → HTTP 502 after ~10.8 s (points still consumed); 10 repos full → 5.3 s; 50 repos tree-only → 5.4 s.
- Sourcegraph stream API, `file:^\.github/plugin/marketplace\.json$ count:all`: 83 matches.
- `github/awesome-copilot` marketplace: 183 plugins, 105 local, 78 external across ~66 repos; `strict` unused. `github/copilot-plugins`: 18 plugins, 2 local, 16 external across 7 repos; uses entry-level `skills`.
- `dotnet/aspnetcore/.github/copilot/settings.json`: `extraKnownMarketplaces` naming `dotnet/arcade-skills` and `dotnet/skills`.

## Appendix B. Sources

- https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference
- https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/plugins-marketplace
- https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/plugins-creating
- https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/plugins-finding-installing
- https://docs.github.com/en/copilot/concepts/agents/about-plugins
- https://code.visualstudio.com/docs/agent-customization/agent-plugins
- https://agent-plugins.org/specification and https://agent-plugins.org/schemas
- https://docs.github.com/en/rest/search/search and https://docs.github.com/en/search-github/github-code-search/about-github-code-search
- https://github.com/github/awesome-copilot and https://github.com/github/copilot-plugins
- User's own verified notes: `jj1985/archer-irm-skills`, `jj1985/plextrac-skills` (dual `.github/plugin` + `.claude-plugin` manifests, Agent Plugins 1.0 `$schema`), `jj1985/skills` Copilot port (legacy manifest preference, extensions, hooks).
