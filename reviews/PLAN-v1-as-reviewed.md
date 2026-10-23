# Copilot Plugin Finder: research, plan and spec

Status: draft v1, 2026-10-22. Research probes in this document were run live against the GitHub REST/GraphQL APIs with the `jj1985` account on 2026-10-22; counts are as returned that day and are approximate (see Risks).

## 1. Goal

Build a repeatable process, and then a small tool, that:

1. Finds every public GitHub repository that GitHub Copilot can register as a plugin marketplace or install as a plugin (CLI, VS Code, Copilot app, cloud agent).
2. Indexes useful metadata about each (repo facts, manifest contents, plugin/skill inventory, which markers matched).
3. Collapses forks and clones onto one canonical repository, keeping the fork/clone count as a popularity signal.
4. Presents the result as a sortable, filterable, graphical page with direct links to each repo, refreshed on a schedule.

Non-goals for v1: private repos, GitHub Enterprise Server, non-GitHub Git hosts (GitLab marketplaces are allowed by Copilot but are out of reach of GitHub search), and installing or executing any plugin.

## 2. What marks a repo as a Copilot marketplace or plugin

### 2.1 Definitive rules (from GitHub's own reference)

Source: [GitHub Copilot CLI plugin reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference), [Creating a plugin marketplace](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/plugins-marketplace), [Creating a plugin](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/plugins-creating), [Plugins for GitHub Copilot](https://docs.github.com/en/copilot/concepts/agents/about-plugins), [Agent plugins in VS Code](https://code.visualstudio.com/docs/agent-customization/agent-plugins), [Agent Plugins Specification 1.0.0](https://agent-plugins.org/specification).

**Marketplace manifest.** `copilot plugin marketplace add OWNER/REPO` succeeds when the repo root contains a `marketplace.json` at one of these paths, checked in this order:

| Order | Path | Notes |
|---|---|---|
| 1 | `marketplace.json` | root; generic filename, needs content validation |
| 2 | `.plugin/marketplace.json` | rare |
| 3 | `.github/plugin/marketplace.json` | the documented Copilot location |
| 4 | `.claude-plugin/marketplace.json` | Claude Code location; Copilot reads it too |

Required fields: `name` (kebab-case, max 64), `owner` `{name, email?}`, `plugins[]` (each with `name` and `source`). Optional `metadata {description, version, pluginRoot}`. A plugin entry's `source` is a relative path string or an object `{source: "github", repo, ref?, sha?, path?}` or `{source: "url", ...}`. The docs state that adding this file "allows Copilot CLI to recognize the repository as a plugin marketplace", so this is the single definitive marketplace marker. VS Code adds npm/PyPI package sources via the Claude marketplace schema.

**Plugin manifest.** `copilot plugin install OWNER/REPO` or `OWNER/REPO:PATH` succeeds when the plugin directory contains `plugin.json` at one of:

| Format | Path(s) | Distinguisher |
|---|---|---|
| Agent Plugins 1.0 / 1.1 | `plugin.json` at plugin root only | `$schema` is exactly `https://agent-plugins.org/schemas/1.0.0/plugin.schema.json` or `.../1.1.0/...`; closed field set (`$schema,name,version,description,author,homepage,repository,license,keywords,extensions`); skills in `skills/*/SKILL.md`; MCP in `mcp.json`; Copilot-specific parts in `com.github.copilot/{agents,commands,rules,hooks/hooks.json,lsp.json}` |
| Legacy Copilot | `.plugin/plugin.json`, `plugin.json`, `.github/plugin/plugin.json`, `.claude-plugin/plugin.json` (checked in this order) | no Agent Plugins `$schema`; optional component-path fields `agents, skills, commands, hooks, extensions, mcpServers, lspServers`; defaults `agents/`, `skills/`, `hooks.json` or `hooks/hooks.json`, `.mcp.json` or `.github/mcp.json`, `lsp.json` |

Only `name` is required in either format. A manifest with an unrecognised Agent Plugins `$schema` version is rejected by the CLI, so the exact URL matters.

**Consumer-side configuration (not a plugin itself, but points at marketplaces).** `.github/copilot/settings.json` (and, for VS Code, `.claude/settings.json`) may contain `extraKnownMarketplaces: {name: {source: {source: "github", repo}}}` and `enabledPlugins: {"plugin@marketplace": true}`. Every `repo` named there is a marketplace by declaration.

**Default and documented marketplaces.** `github/awesome-copilot` (built in, cannot be removed), `github/copilot-plugins` (formerly default, now opt-in), `anthropics/claude-code`, `claudeforge/marketplace`. The first two are seeds and also list external repos: awesome-copilot's manifest has 183 plugins of which 78 point at 60-odd other repos via `source` objects; copilot-plugins has 18 plugins of which 16 are external. Those referenced repos are plugins by declaration even if they carry no manifest of their own at the root.

### 2.2 Markers, measured

Code-search hit counts on 2026-10-22 (REST `search/code`, authenticated; one hit = one file, so repos are fewer; default results exclude forks):

| ID | Marker (code-search query) | Hits | Reliability | Meaning |
|---|---|---|---|---|
| M-GH | `path:.github/plugin filename:marketplace.json` | 884 (+419 with `fork:only`) | definitive when at repo root | Copilot-native marketplace |
| M-CL | `path:.claude-plugin filename:marketplace.json` | ~43,900 | definitive for installability, but Claude-first | Claude marketplace, Copilot-compatible |
| M-PL | `path:.plugin filename:marketplace.json` | 24 | definitive | rare legacy location (e.g. `OpenHands/extensions`, `Azure/azure-functions-skills`) |
| M-ROOT | `filename:marketplace.json "plugins" "owner" -path:.claude-plugin -path:.github -path:.cursor-plugin -path:.plugin -path:.agents` | 8,320 before the `.agents` exclusion, almost all `.agents/plugins/marketplace.json` (Codex CLI); root-only residue unknown | heuristic until verified at root and content-validated | root marketplace |
| X-CODEX | `path:.agents/plugins filename:marketplace.json` | ~8,000 | Codex CLI format, not read by Copilot; co-occurrence attribute only | attribute |
| M-GHS | `path:.github/plugins filename:marketplace.json` | 24 | false positive: wrong dir name (`plugins`), Copilot will not read it | exclude, but worth a "misconfigured" flag |
| P-AP | `agent-plugins.org filename:plugin.json` | ~10,560 files | definitive for Agent Plugins format (many are plugins inside marketplaces, so repo count is much lower) | Agent Plugins 1.0/1.1 plugin |
| P-GH | `path:.github/plugin filename:plugin.json` | 291 | definitive (legacy Copilot) | legacy plugin repo |
| P-GH-ext | `path:.github/plugin filename:plugin.json extensions` | 13 | definitive Copilot-specific (extensions = Copilot SDK code) | legacy plugin with extensions |
| P-PL | `path:.plugin filename:plugin.json` | 193 | definitive (legacy location 1; e.g. `vercel/vercel-plugin`, `meta-quest/agentic-tools`) | legacy plugin repo |
| P-CL | `path:.claude-plugin filename:plugin.json` | ~32,200 | definitive for installability | Claude plugin, Copilot-compatible |
| P-ROOT | root `plugin.json` without schema | very noisy (Jenkins, Minecraft, Obsidian, etc. all use `plugin.json`) | heuristic: accept only if sibling `skills/`, `agents/`, `hooks.json`, `.mcp.json`, `com.github.copilot/` exists or manifest has a component-path field | legacy plugin |
| S-COP | `path:com.github.copilot` | 515 files | definitive Copilot-specific signal (Agent Plugins client extension dir) | strengthens P-AP |
| S-COPX | `filename:plugin.json "com.github.copilot"` | 164 | definitive Copilot-specific signal in `extensions` | strengthens P-AP |
| S-SET | `path:.github/copilot filename:settings.json extraKnownMarketplaces` | 102 repos | definitive pointer to marketplaces (consumer side) | discovery vector, not a plugin |
| S-SET2 | `... enabledPlugins` | 119 repos | pointer to `plugin@marketplace` names | discovery vector |
| S-HOOK | `path:.github/hooks filename:hooks.json` | 619 | not a plugin marker (repo-level Copilot hooks); ignore for inclusion | none |
| X-CUR | `path:.cursor-plugin filename:marketplace.json` | 2,228 | Cursor format, Copilot does not read it; useful only as a co-occurrence attribute | attribute |
| T-* | repo topics `copilot-plugin` (50), `copilot-plugins`, `copilot-marketplace` (1), `agent-plugins` (368), `claude-code-plugin` (11,553), `claude-code-marketplace` (549) | — | heuristic; a topic alone never includes a repo | discovery + attribute |

Important nuance found by probing: `path:.github/plugin` matches anywhere in the tree, for example `jj1985/worktools` has `soar-toolkit/.github/plugin/marketplace.json`. Copilot only reads the repository root for marketplaces (`marketplace add` takes `owner/repo` with no subpath), so nested hits are not registrable marketplaces. They may still be installable plugins via `owner/repo:path`. Every candidate therefore needs a verification step that checks the exact root path (section 3.4).

Also observed: `microsoft/aspire-skills` keeps its manifests under `.github/plugins/aspire-skills/.claude-plugin/marketplace.json`, i.e. not a root marketplace at all. These are real projects that users will expect to see, so the UI should carry a "misplaced manifest" flag rather than silently dropping them.

### 2.3 Inclusion tiers (the definition the tool will use)

| Tier | Definition | Expected size |
|---|---|---|
| A. Copilot-native marketplace | root `.github/plugin/marketplace.json` (or `.plugin/`, or validated root `marketplace.json`) | ~900 source repos + ~400 forks |
| B. Copilot-native plugin repo | Agent Plugins manifest at root, or legacy manifest at `.github/plugin/plugin.json` / `.plugin/plugin.json`, or validated root `plugin.json`, or repo referenced by a Tier A/C marketplace `source` object | low thousands |
| C. Copilot-compatible (Claude format) marketplace or plugin | only `.claude-plugin/marketplace.json` or `.claude-plugin/plugin.json` | ~45k+ repos |
| D. Declared-only | named in some `extraKnownMarketplaces` or marketplace `source` but no manifest found at verification | small; shown with a warning |

Default UI view: Tiers A+B (what the user calls "Copilot marketplace plugins"). Tier C is one toggle away. The scanner collects all tiers because de-duplication needs the whole population (most Tier A forks are forks of awesome-copilot, and many Tier A repos also carry Tier C files).

## 3. Discovery strategy

### 3.1 Search surfaces and their limits (verified)

| Surface | Use | Limits observed |
|---|---|---|
| REST `GET /search/code` (`gh search code`, `gh api search/code`) | primary: filename/path/content markers | 1,000 results per query (page 11 returns HTTP 422 "Cannot access beyond the first 1000 results"); 10 requests/min for this token even though authenticated; `per_page` max 100; only default branches; files under 384 KB; forks excluded unless `fork:true`/`fork:only` (both returned the same 419 here, so run `fork:only` as a separate pass); qualifiers available: `in, user, org, repo, path, filename, extension, language, size, fork`; date qualifiers are silently ignored (`pushed:>2026-10-01` returned 0); `sort=indexed` is available for newest-first incremental sweeps; totals are estimates (three disjoint `size:` buckets of M-CL summed to 49,232 against a reported 43,904) |
| REST `GET /search/repositories` | topic and description heuristics; supports `created:`/`pushed:`/`stars:` partitioning | 1,000 cap, 30 req/min |
| GraphQL `search` | repositories only (SearchType enum: ISSUE, REPOSITORY, USER, DISCUSSION; no CODE) | 1,000 cap |
| GraphQL `repository(...)` with aliases | verification and metadata: 50–100 repos per query, each with `object(expression:"HEAD:<path>")` blobs and tree listings | cost 1 point per query in the probe; 5,000 points/hour, so ~250k repo-verifications/hour theoretical |
| REST contents / git trees | recursive tree for skill counting when GraphQL depth is insufficient | 5,000 req/hour core |
| Sourcegraph public stream API (`sourcegraph.com/.api/search/stream`, no auth needed) | completeness cross-check only | indexed only 83 files for `^\.github/plugin/marketplace\.json$` versus 884 on GitHub, so it is a sample, not a census |
| GH Archive / BigQuery `githubarchive` | change detection (PushEvent for known repos), new-repo detection (CreateEvent) | events carry no file paths, so they cannot find markers directly; `bigquery-public-data.github_repos` contents are a stale snapshot; costs money per TB scanned |
| Existing catalogs | seeds and recall checks: awesome-copilot plugin directory, `github/copilot-plugins`, agenticskills.io, `louis030195/awesome-agent-plugins`, `ilderaj/agent-plugin-marketplace`, `webrix-ai/plugin-marketplace-wizard` | hand-curated, lag behind |

Index lag measured: `jj1985/plextrac-skills` (created 2026-10-20) was in code search by 2026-10-22; `jj1985/skills` (fork made 2026-10-21, 0 stars) is not findable even with `fork:true`, consistent with GitHub's rule that low-value forks are not indexed. Expect a 1–3 day lag for new repos and no coverage for most zero-star forks (which is fine for de-dup; they are not canonical anyway).

### 3.2 Query plan

Each marker in 2.2 becomes one or more queries. A query that reports more than ~900 hits is split until each slice is under the cap:

1. Primary split axis: `size:` on the matched file in bytes (`size:<400`, `size:400..600`, …). Marketplace files cluster between 300 B and 3 KB, so a geometric ladder of 15–25 buckets suffices for M-CL; bisect any bucket still over the cap. Because totals are approximate, treat a bucket as complete only when page 10 returns fewer than 100 items.
2. Secondary axes when a single size bucket is still over the cap: `language:JSON` vs not, `user:`/`org:` for the largest owners (take owner histogram from already-fetched pages, then run `-user:` exclusions is not supported, so instead run per-owner queries for the top owners and exclude those owners client-side from the generic bucket), `path:` variants.
3. Forks: repeat every query with `fork:only`.
4. Incremental: run every base query with `sort=indexed&order=desc` and stop paging when a full page consists of already-known `(repo, path, sha)` triples.
5. Budget: 10 req/min means a complete M-CL sweep (≈45 slices × 10 pages) is ~8 hours of wall-clock if nothing else runs; Tier A+B markers are ~30 requests. Plan: Tier A+B every night, incremental Tier C nightly, full Tier C weekly, spread across the week.

### 3.3 Secondary discovery (graph expansion)

For every verified marketplace, parse its manifest and enqueue each external `source.repo`. For every `.github/copilot/settings.json` hit, enqueue each `extraKnownMarketplaces[*].source.repo` and the marketplace half of each `enabledPlugins` key. For each plugin manifest, enqueue `repository` and `homepage` if they point at a different GitHub repo. Topic searches (T-*) enqueue candidates too. Repeat until the frontier is empty. Everything enqueued goes through verification; declared-but-unverifiable repos become Tier D.

### 3.4 Verification (the step that turns a hit into a record)

One GraphQL query per batch of 50 candidates fetches, per repo: the repository object (3.5 fields below), `object(expression:"HEAD:<path>")` for all eight manifest paths (returns `oid`, `byteSize`, `text` for small blobs), root tree entries, and `plugins/` tree entries. A record is admitted to Tier A/B/C only if the blob exists at the exact root path and parses as JSON with the required fields. Nested hits are recorded with `root=false` and a `misplaced_manifest` flag.

## 4. Metadata to collect

### 4.1 Cheap (one GraphQL batch, no extra calls)

`nameWithOwner`, `databaseId` (stable key across renames), `url`, `description`, `owner.login`, `owner.__typename` (User/Organization), `isFork`, `parent.nameWithOwner`, `isArchived`, `isTemplate`, `isMirror`, `isDisabled`, `stargazerCount`, `forkCount`, `watchers.totalCount`, `issues(states:OPEN).totalCount`, `createdAt`, `pushedAt`, `updatedAt`, `homepageUrl`, `licenseInfo.spdxId`, `primaryLanguage.name`, `repositoryTopics`, `latestRelease{tagName,publishedAt}`, `defaultBranchRef.name`, head commit `oid`, root `tree.oid`, `history.totalCount`, `diskUsage`, README blob `oid` and `byteSize`, the eight manifest blobs (`oid`, `byteSize`, `text` when under ~100 KB), root tree entry names, `plugins/` entry names, and the per-repo `.github/copilot/settings.json` blob.

Derived without further calls: `marketplace_name`, `marketplace_owner`, `plugin_count_declared`, list of declared plugins (`name, version, description, source, keywords, category`), `external_plugin_count`, `format` (agent-plugins-1.0 / 1.1 / legacy / claude), Copilot-specific flags (`has_com_github_copilot_dir`, `has_extensions`), `has_license`, `readme_present`, `markers_matched[]`, `tiers[]`.

### 4.2 Expensive (second pass, prioritised by stars and tier)

- Per-plugin inventory: for each local `source` path, fetch the plugin dir tree (GraphQL nested `object { ... on Tree { entries { name object { ... on Tree { entries }}}}}` two levels deep covers `skills/<name>/SKILL.md`, `agents/*.agent.md`, `commands/`, `hooks.json`, `mcp.json`, `com.github.copilot/*`) and count skills, agents, commands, hooks, MCP servers, extensions. Repos with more than ~20 plugins fall back to one REST recursive tree call.
- SKILL.md frontmatter (`name`, `description`) for the search index: fetch only for Tier A/B and for Tier C repos above a star threshold.
- README excerpt: first 600 characters of the README blob text (fetched in the same GraphQL query when small).
- Manifest validation result against the published JSON schema (`agent-plugins.org/schemas/1.x/plugin.schema.json`) and against the Copilot field rules (name constraints, closed schema) so the UI can show "valid / warnings".

### 4.3 Record schema (logical)

```
repo            id (databaseId), full_name, owner, owner_type, description, homepage,
                stars, forks, watchers, open_issues, is_fork, parent, source_repo,
                is_archived, is_template, is_mirror, default_branch, license, language,
                topics[], created_at, pushed_at, updated_at, latest_release, latest_release_at,
                head_sha, root_tree_sha, commit_count, readme_sha, readme_excerpt,
                tiers[], markers[], root_manifest_paths[], misplaced_manifest(bool),
                marketplace{name, owner, description, version}, format, copilot_specific(bool),
                plugin_count, skill_count, agent_count, hook_count, mcp_count, extension_count,
                external_plugin_count, schema_valid, schema_warnings[],
                cluster_id, is_canonical, clone_count, known_forks_count,
                first_seen, last_seen, last_verified, missing_since, status
plugin          repo_id, name, version, description, source_kind(local/github/url/npm/pypi),
                source_repo, source_path, keywords[], category, format, skill_count, ...
skill           plugin_id, name, description, path
marker_hit      repo_id, marker_id, path, blob_sha, first_seen, last_seen
scan            id, started, finished, queries_run, requests_used, repos_seen, errors
```

## 5. De-duplication rules

### 5.1 Signals, cheapest first

1. `isFork` with `parent` → fork edge (definitive).
2. Identical `root_tree_sha` → identical whole tree (definitive clone, including template-generated and re-pushed copies with rewritten history).
3. Identical marketplace or plugin manifest blob `oid` → same manifest bytes (strong; forks that only change README still match here).
4. Identical README blob `oid` (strong; the oid is a content hash, so no download is needed).
5. Manifest identity: same `(marketplace.name, owner.name, sorted plugin names)` or same `(plugin.name, version, description)` (medium; catches re-exports and renamed copies).
6. Structural fingerprint: hash of sorted plugin dir names + skill names + agent names (medium).
7. First-commit SHA equality (strong for history-preserving clones; obtained with the GraphQL history cursor trick `after:"<head_oid> <totalCount-2>"` or one REST call; only computed for repos that already matched a medium signal, to keep it cheap).
8. `repository`/`homepage` field in a manifest pointing at another indexed repo → "derived from" edge (medium).

### 5.2 Clustering

Union-find over definitive and strong edges; medium edges join clusters only when two independent medium signals agree (for example manifest identity and structural fingerprint). Mirrors (`isMirror`) and template repos (`isTemplate`) are recorded but a template's descendants are flagged `from_template` rather than treated as clones of each other when they have since diverged (tree SHA differs).

Plugin-level duplicates are tracked separately: the same plugin (by manifest blob oid or name+version) appearing in several marketplaces is one plugin with many distributors. That matters because awesome-copilot re-lists ~60 external repos.

### 5.3 Canonical choice (tie-breakers, in order)

1. The fork network root (`parent == null`; for forks, GitHub's `source` repo).
2. The repo named by the manifest's own `repository`/`homepage` field, if it is in the cluster.
3. The repo that a seed marketplace (`github/awesome-copilot`, `github/copilot-plugins`) points at.
4. Oldest `createdAt`.
5. Most stars.
6. Organisation over user, then not archived, then alphabetical as a last resort.

The canonical record carries `clone_count` (non-fork cluster members) and `known_forks_count` (GitHub's `forkCount`, plus indexed fork members). Non-canonical members stay in the database with `is_canonical=false` so the UI can list them in the detail panel and a "show duplicates" toggle can reveal them.

## 6. Storage and refresh

- Store: one SQLite file (`data/index.sqlite`) with the tables in 4.3, written by the scanner; plus exported `site/data/repos.json.gz` (table columns only, ~40 fields) and per-repo shards `site/data/repo/<id>.json` (manifests, plugins, skills, cluster members) for lazy loading. Parquet export is optional for analysis.
- Identity: GitHub `databaseId` is the primary key so renames and transfers do not create duplicates; `full_name` is updated on each verification.
- Provenance: every record keeps `first_seen`, `last_seen` (last time any discovery query returned it), `last_verified` (last successful GraphQL fetch), and a list of `marker_hit` rows.
- Drop-out rule: a repo missing from two consecutive full sweeps of all its markers gets `missing_since`; a verification fetch then decides: 404/null → `status=gone`; marker file removed → `status=demarked` (kept, hidden by default); still present → index lag, keep active. Nothing is deleted; `gone` rows are retained for history charts.
- Snapshots: a daily `repo_daily(repo_id, date, stars, forks)` table enables growth charts; at ~50k rows/day it stays small.
- Schedule: nightly Tier A+B full sweep plus Tier C incremental (`sort=indexed`), weekly Tier C full sweep spread over seven nights, monthly completeness check against Sourcegraph and topic searches, with the diff logged.

## 7. UI/UX

### 7.1 Delivery options compared

| | Static site (recommended) | Small server app |
|---|---|---|
| Shape | Single-page app built from `repos.json.gz`; GitHub Pages; scanner runs in GitHub Actions and commits data | FastAPI/Flask + SQLite, server-side filtering, HTMX or React front end |
| Scale | 1–3k rows (Tier A+B) trivially; 50k rows (Tier C) needs column pruning, gzip (~5–8 MB) and a virtualised table, still feasible | unlimited |
| Ops | zero: no host, no auth, free | needs a host, uptime, token handling |
| Freshness | as fresh as the last Action run | same, data still comes from the scheduled scanner |
| Sharing | one URL, works offline once loaded | one URL |
| Search | client-side (MiniSearch) over name, description, plugin and skill names | SQLite FTS5 |

Recommendation: static site, with Tier C loaded lazily behind a toggle (a second, larger data file). Revisit only if Tier C grows past ~150k rows or server-side features (user accounts, alerts) become wanted.

### 7.2 Features

- Table (TanStack Table or Tabulator, virtualised): columns full name (link), owner, tier badge, format, stars, forks, clones, plugins, skills, language, license, created, pushed, last verified, flags (archived, template, misplaced manifest, schema warnings).
- Filters: text search; stars range; owner type; language; has license; archived; template; fork count range; clone count; tier; format (agent-plugins / legacy / claude); Copilot-specific components present (agents, hooks, extensions, MCP, LSP); marker type; created and pushed date ranges; "show non-canonical duplicates"; "verified in last N days".
- Sort on every column, multi-sort with shift-click.
- Charts (dataviz guidance applies when built): stars distribution (log histogram); repos first seen per week (growth); plugins per owner (top 20 bar); language mix; format split (agent-plugins vs legacy vs claude) over time; component mix (skills/agents/hooks/MCP) stacked bar; fork/clone concentration (how many clusters hold >5 members).
- Detail panel (slide-over): description, README excerpt, marketplace metadata, plugin list with versions and per-plugin component counts, skills list, matched markers with file links (`https://github.com/<repo>/blob/<branch>/<path>`), schema validation result, cluster members (forks and clones) with links, install snippets (`copilot plugin marketplace add owner/repo`, `copilot plugin install name@marketplace`, `copilot plugin install owner/repo:path`), topics, license, release.
- Exports: CSV and JSON of the current filtered view; permalink encoding the filter state in the URL hash.
- "Last scanned" indicator in the header: scan finish time, repos verified, requests used, and a link to the scan log; per-row `last_verified` tooltip.
- Accessibility: keyboard navigation of the table, visible focus, colour not the only encoding for tier.

## 8. Architecture and tech choices

- Language: Python 3.12 (already used by the user with `PYTHONUTF8=1`), `httpx` for REST/GraphQL with a token-bucket limiter per resource (code search 10/min, search 30/min, GraphQL points), `sqlite3` standard library, `jsonschema` for manifest validation, `pyyaml` for SKILL.md frontmatter.
- CLI: `cpf discover` (run marker queries, write `marker_hit`), `cpf expand` (graph expansion), `cpf verify` (GraphQL batches), `cpf enrich` (expensive pass), `cpf dedup`, `cpf export`, `cpf scan` (all of the above with budgets), `cpf stats`.
- Auth: a fine-grained PAT with public-repo read scope stored as an Actions secret. Open question: whether the Actions-provided `GITHUB_TOKEN` is accepted by `search/code`; if not, the PAT is required.
- Runner: GitHub Actions nightly cron with job-level time limits; artifacts committed to a `data` branch; Pages deploys `site/`.
- Front end: Vite + vanilla TypeScript, TanStack Table, Observable Plot or Chart.js, MiniSearch; no backend.
- Repo layout: `scanner/` (Python package), `site/` (front end), `data/` (SQLite and exports, possibly a separate branch), `docs/PLAN.md`.

## 9. Risks and limits

- Approximate counts and overlapping slices: the search index returns estimates; de-duplicate hits by `(repo id, path)` and never trust `total_count` for completeness, only the "last page short" condition.
- 1,000-result cap plus 10 req/min: Tier C full sweeps take hours; spread them out and make everything resumable.
- Index lag and gaps: new repos take 1–3 days; zero-star forks are mostly unindexed; repos inactive for a long time can drop out of the code-search index even though they still exist; secondary discovery via marketplace references partially compensates.
- False positives: nested manifests (not registrable), test fixtures and tutorials, template repos and their generated copies, `.github/plugins/` typos, generic `plugin.json`/`marketplace.json` from other ecosystems. Verification at the exact root path and JSON validation handle most; a manual deny-list handles the rest.
- False negatives: marketplaces at root `marketplace.json` with unusual content, plugins only reachable via `owner/repo:path`, GitLab/other hosts, private repos.
- Scale asymmetry: Tier C is 40–50x Tier A+B and overwhelmingly Claude-first; keep it behind a toggle so the "Copilot" view stays useful.
- Rate-limit incidents: secondary rate limits on bursts; use conditional requests (ETag) for repeat fetches and back off on 403/429.
- Content hazards: manifests and READMEs are third-party data; never execute anything, escape everything in the UI, and keep only short excerpts.
- Moving target: GitHub added Agent Plugins 1.1 recognition and changed default marketplaces within weeks; the marker table must be data-driven (a `markers.yaml`) so additions do not need code changes.

## 10. Open questions

1. Should Tier C (Claude-format) be scanned fully from day one, or only via the incremental path with full sweeps monthly, given the cost?
2. Primary entity in the UI: repository (simple, what the user asked for) or plugin (more precise, since marketplaces bundle many plugins and the same plugin appears in several)? Current plan: repository table with a plugin sub-table and a plugin-level view in phase 4.
3. Hosting: GitHub Pages under `jj1985` with Actions, or local-only runs with a static file opened from disk?
4. Token: is `GITHUB_TOKEN` in Actions sufficient for `search/code`, or is a PAT required?
5. Should repos that merely reference marketplaces (`extraKnownMarketplaces` consumers) be shown as a separate "adopters" dataset? It is a cheap by-product and a good adoption signal.
6. Do we want the count of VS Code-only package sources (npm/PyPI) and Cursor manifests as attributes, or drop them to keep scope tight?
7. How aggressive should medium-signal clustering be? Over-merging hides real projects; under-merging inflates counts. Needs a sample audit after phase 2.

## 11. Phased implementation plan

- Phase 0 (done in this research): marker census, cap and rate-limit verification, GraphQL batch pattern, fork and partition semantics.
- Phase 1, crawler core (2–3 days): `markers.yaml`, discovery with size-partitioning and resumable paging, `marker_hit` persistence, GraphQL verification for Tier A+B, SQLite schema, `cpf stats`. Exit criterion: Tier A+B fully enumerated with manifests parsed, nightly run under 30 minutes.
- Phase 2, expansion and de-dup (2 days): graph expansion from manifests and settings files, Tier D, clustering with definitive and strong signals, canonical selection, sample audit of 50 clusters.
- Phase 3, static UI (2–3 days): export, table, filters, detail panel, three charts, CSV/JSON export, last-scanned indicator; deploy to Pages.
- Phase 4, Tier C at scale and enrichment (3–5 days, mostly machine time): partitioned sweeps, incremental `sort=indexed` runs, per-plugin inventory and skills, schema validation, daily star snapshots and growth charts, plugin-level view.
- Phase 5, hardening: completeness checks against Sourcegraph and topics, deny-list, alerts on scan failure, documentation, and a `cpf diff` that reports new/changed/gone repos between scans.

## Appendix A. Probe log (2026-10-22)

- `gh api rate_limit`: `code_search` limit 10/min, `search` 30/min, `core` 5000/h, `graphql` 5000 points/h (authenticated as jj1985).
- `search/code` page 11 at `per_page=100`: HTTP 422 "Cannot access beyond the first 1000 results".
- `path:.github/plugin filename:marketplace.json`: 884; first 100 results contain 0 forks; `fork:true` and `fork:only` both 419 (all forks, e.g. `burkeholland/awesome-copilot`).
- `path:.claude-plugin filename:marketplace.json`: 43,904; `size:<600` 25,024; `size:600..1200` 15,712; `size:>1200` 8,496; `pushed:>2026-10-01` 0 (qualifier unsupported).
- `user:jj1985 filename:marketplace.json`: 5 files across 3 repos, including a nested `soar-toolkit/.github/plugin/marketplace.json` in `jj1985/worktools`.
- `repo:jj1985/skills filename:plugin.json fork:true`: 0 (unindexed fork); `repo:jj1985/plextrac-skills filename:marketplace.json`: 2 (indexed within two days of creation).
- GraphQL `SearchType` enum: ISSUE, ISSUE_ADVANCED, ISSUE_SEMANTIC, ISSUE_HYBRID, REPOSITORY, USER, DISCUSSION.
- GraphQL batch of two repositories with 7 `object()` lookups each and tree listings: `rateLimit.cost` 1.
- Sourcegraph stream API, `file:^\.github/plugin/marketplace\.json$ count:all`: 83 matches.
- `github/awesome-copilot` marketplace: 183 plugins, 105 local, 78 external across ~60 repos. `github/copilot-plugins`: 18 plugins, 2 local, 16 external across 7 repos.
- `dotnet/aspnetcore/.github/copilot/settings.json`: `extraKnownMarketplaces` naming `dotnet/arcade-skills` and `dotnet/skills`.
- `path:.plugin filename:marketplace.json`: 24; `path:.plugin filename:plugin.json`: 193; `path:.claude-plugin filename:plugin.json`: 32,192; `filename:marketplace.json "plugins" "owner"` excluding `.claude-plugin/.github/.cursor-plugin/.plugin` paths: 8,320, dominated by `.agents/plugins/marketplace.json` (Codex CLI convention).

## Appendix B. Sources

- https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference
- https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/plugins-marketplace
- https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/plugins-creating
- https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/plugins-finding-installing
- https://docs.github.com/en/copilot/concepts/agents/about-plugins
- https://code.visualstudio.com/docs/agent-customization/agent-plugins
- https://agent-plugins.org/specification and https://agent-plugins.org/schemas
- https://docs.github.com/en/rest/search/search
- https://github.com/github/awesome-copilot and https://github.com/github/copilot-plugins
- User's own verified notes: `jj1985/archer-irm-skills`, `jj1985/plextrac-skills` (dual `.github/plugin` + `.claude-plugin` manifests, Agent Plugins 1.0 `$schema`), `jj1985/skills` Copilot port (legacy manifest preference, extensions, hooks).
