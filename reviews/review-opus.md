Reviewer model: Claude Opus (via Agent tool), date 2026-10-22

# Independent review of PLAN.md (Copilot Plugin Finder, draft v1)

## How I checked things

Every factual claim below is tagged:

- **[verified: how]** means I checked it today.
- **[docs]** means I read it today on docs.github.com, code.visualstudio.com or agent-plugins.org.
- **[recalled]** means it comes from memory and was not re-checked; confirm it before relying on it.

Probes I ran, all read-only, as the authenticated `gh` user:

- 6 `search/code` calls (the limit I was given).
- 1 REST `search/repositories` call.
- GraphQL introspection.
- 6 GraphQL verification batches of 10, 25, 50 and 100 repositories.
- 3 REST contents/repo calls.

Overall view: the plan is well researched, and its marker census is the most valuable part. It has four weaknesses:

1. **The GraphQL verification design does not work as written.** Batches of 50 repos with 8 blob lookups time out (details in topic 3).
2. **Refresh and drop-out depend on code search,** which is the least reliable surface. The plan's incremental key, `sort=indexed`, is deprecated.
3. **De-duplication will over-merge** on boilerplate blobs and on divergent forks. It also misses a definitive edge that GraphQL already exposes (`templateRepository`).
4. **Several discovery vectors that return thousands of hits are missing.**

---

## 1. Plugin markers (section 2)

### 1.1 Errors

**"Only `name` is required in either format" (2.1, under the plugin manifest table) is wrong for Agent Plugins.**
- The Copilot CLI reference and the Agent Plugins spec both list **`$schema` and `name` as required** for Agent Plugins 1.0 [docs: cli-plugin-reference, agent-plugins.org/specification].
- Agent Plugins `name` rule: 1–64 chars, lowercase letters, digits, `-` and `.`; must start and end alphanumeric; no `--` or `..`.
- Legacy `name` rule: kebab-case, letters, digits and hyphens only, max 64 [docs].
- Change: give each format its own required-field and name rules. Validate them separately in 4.2's "valid / warnings".

**"Closed field set" for Agent Plugins (table in 2.1) is too strong.**
- The spec says unknown top-level fields are "reported and ignored", not rejected [docs: agent-plugins.org].
- Change: treat unknown fields as a warning, not an exclusion. Keep the separate claim that an unrecognised `$schema` version is rejected by the CLI. I did not verify that claim, so mark it "observed on CLI v1.0.101" if that is where it came from.

**Legacy plugin fields are incomplete.**
- The reference lists legacy optional fields that the plan omits: `category` and `tags`, plus component paths. Marketplace plugin entries also accept `commands, agents, skills, hooks, mcpServers, lspServers, strict` [docs].
- `github/copilot-plugins` really uses `skills` inside marketplace entries [verified: fetched its `.github/plugin/marketplace.json`].
- Change: add `category`, `tags`, `strict` and the entry-level component fields to the parser and to the `plugin` table.

**`strict` matters for inventory.**
- In the Claude marketplace schema, `strict: false` means the marketplace entry *is* the plugin manifest, so the plugin directory may have no `plugin.json` [recalled, Claude Code docs]. Copilot's reference accepts `strict` [docs].
- Consequence: P-* markers and per-plugin inventory will undercount plugins that only exist as marketplace entries.
- Change (4.2): derive the plugin inventory from marketplace entries first. Treat a per-plugin `plugin.json` as optional enrichment.
- Neither seed uses `strict` today [verified: 0 of 183 and 0 of 18 entries], but Claude-format marketplaces in Tier C will.

**Source types (2.1).**
- Copilot documents `github` and git-URL `url` sources with an optional 40-char `sha` [docs].
- VS Code adds npm/PyPI packages and accepts HTTPS and SCP-style git remotes and `file:///` for marketplaces [docs: VS Code agent-plugins].
- The Claude schema has further kinds (`git-subdir`, `npm`, `pip`) [recalled].
- Change: make `source_kind` an open enum that stores unknown kinds verbatim, and add a `source_host` column. Non-GitHub URL sources then show up as "external host" rather than being dropped.

**Default marketplaces (2.1): the docs contradict each other.**
- `concepts/agents/about-plugins` says two are included by default, `copilot-plugins` and `awesome-copilot` [docs].
- `plugins-finding-installing` says only `awesome-copilot` is registered by default [docs].
- The plan's "formerly default, now opt-in" matches the second page only.
- Change: record both URLs and the date, and treat both repos as seeds either way.

**Cloud agent is in the goal (section 1) but not in the marker rules.**
- `about-plugins` lists four surfaces: the Copilot app, Copilot CLI, Copilot cloud agent, and VS Code. It warns that component support varies by surface [docs].
- None of the manifest pages describes how the cloud agent picks plugins up. The likeliest path is repo-level `.github/copilot/settings.json` `enabledPlugins` [unverified inference].
- VS Code reads Copilot, Claude and "legacy OpenPlugin" formats but does not publish its path precedence [docs].
- Change: add a per-surface support matrix to 2.1 (CLI / VS Code / app / cloud agent × manifest path × component type). Mark each cell "docs", "observed" or "unknown", and carry a `surfaces[]` field per record. Otherwise "can Copilot install it" is really only "can Copilot CLI install it".

### 1.2 Gaps

**Manifest precedence and shadowing.**
- The CLI checks marketplace paths in the order `marketplace.json`, `.plugin/`, `.github/plugin/`, `.claude-plugin/` [docs, matches the plan].
- Legacy plugin paths are checked in the order `.plugin/plugin.json`, `plugin.json`, `.github/plugin/plugin.json`, `.claude-plugin/plugin.json`. A root Agent Plugins manifest beats all of these [docs].
- So a stray root `plugin.json` (Obsidian, Jenkins, Minecraft) or root `marketplace.json` from another ecosystem can **shadow** a valid `.github/plugin/` or `.claude-plugin/` manifest. Whether the CLI falls through after a parse failure is undocumented.
- Change: record `effective_manifest_path` (the first existing path in CLI order) and a `shadowed_manifests[]` list per record. Flag "effective manifest invalid, valid manifest shadowed" as its own warning. This is cheap because the root tree listing already shows which files exist.

**Filename matching is not exact.**
- `filename:marketplace.json` matched `superset-sh/superset/.agent-marketplace.json` [verified, root probe below].
- Change: section 3.4 must compare the exact basename. Note in 2.2 that every hit count includes some suffix matches.

**Root-level anchoring exists, and M-ROOT does not need the exclusion chain.**
- `path:/ filename:marketplace.json plugins owner` returned **399** hits, all at repository root: `microsoft/azure-container-apps`, `microsoft/power-platform-skills`, `microsoft/work-iq`, `microsoft/agent-host-protocol`, ... [verified].
- Change: replace the M-ROOT query with `path:/ filename:marketplace.json plugins owner`. Add a P-ROOT query `path:/ filename:plugin.json` with content terms (`skills`, `agents`, `hooks`, `mcpServers`, `agent-plugins.org`).
- Spike to run: whether `path:/.github/plugin` anchors too. If it does, M-GH and P-GH lose their nested false positives at query time.

**Root `SKILL.md` fallback.**
- The reference describes a root `SKILL.md` fallback for legacy plugins without a `skills/` directory [docs].
- Change: count it in `skill_count` and in the P-ROOT acceptance heuristic.

**Missing consumer-side markers.**
- VS Code reads `extraKnownMarketplaces` / `enabledPlugins` from **both** `.claude/settings.json` and `.github/copilot/settings.json` [docs].
- `path:.claude filename:settings.json extraKnownMarketplaces` returned **4,104** hits (ag-grid, nx-console, ...) [verified], against 102 for the `.github/copilot` variant in the plan.
- `.vscode/settings.json` with `chat.plugins.marketplaces` returned **19** [verified].
- Change: add **S-SET-CL** and **S-VSC** to 2.2 as discovery vectors.

**Missing README marker.**
- `"copilot plugin marketplace add" extension:md` returned **4,632** hits [verified].
- Change: add **S-README** for `"copilot plugin marketplace add"`, `"copilot plugin install"` and `"/plugin marketplace add"`, and extract `owner/repo` tokens. This is the largest secondary-discovery vector I found.

**Tier naming.**
- Tier C (Claude-format) is just as installable by Copilot as Tier A. The tiers describe *authoring intent*, not installability.
- Change: rename the tiers so users do not read Tier C as "not Copilot":
  - "Copilot-authored"
  - "Copilot-installable (Claude format)"
  - "Declared only"
- Separately, show `copilot_specific` (has `com.github.copilot/`, `extensions`, `.github/plugin`) as a badge.

**Execution-risk signals.**
- Hooks run shell commands, MCP servers launch processes, and `extensions` runs JS through the Copilot SDK [docs + recalled].
- Change: add a derived `executes_code` flag (hooks, MCP, LSP, extensions present). Users will want to filter on it.

**PII in manifests.**
- `owner.email` and `author.email` are personal data.
- Change: keep them in SQLite if needed, but strip them from `site/data` exports.

---

## 2. Discovery (section 3)

### 2.1 Errors and corrections

**`sort=indexed` is being retired.**
- The REST docs mark the code-search `sort` parameter as **"This field is closing down."** [docs: rest/search/search].
- 3.2 step 4 and section 6 make it the backbone of incremental Tier C.
- Change: keep it opportunistically, but design incrementality so it does not depend on it (see 2.3 below). Add a scanner health check that alerts when `sort=indexed` stops changing result order.

**`fork:true` behaves like `fork:only`.**
- `path:.github/plugin filename:marketplace.json fork:true` returned 419 again, all forks [verified]. This confirms the probe log, and it contradicts the documented meaning of `fork:true` (forks included alongside sources).
- Change: note this in 3.1 as observed behaviour, not documented behaviour. Always run the source pass and the `fork:only` pass separately.

**Fork coverage in search is tiny. Never treat it as a fork census.**
- `github/awesome-copilot` has `forks_count` **5,191** and `network_count` 5,191 [verified, REST]. Code search returns 419 fork hits, roughly 8%.
- "~400 forks" in Tier A is therefore a search artefact.
- Change: always take fork counts from `forkCount`. To find forks that became independent projects, enumerate `forks(first:100, orderBy:{field:STARGAZERS, direction:DESC})` via GraphQL for canonical repos. Verify only forks with ≥1 star or `pushedAt` well after `createdAt`.

**`-user:` exclusion may work.**
- `path:.github/plugin filename:marketplace.json -user:github` was accepted, returning 888 against 884 [verified]. The count difference is estimate noise, so whether the exclusion applied is unproven.
- 3.2 step 2 states "`-user:` exclusions is not supported".
- Change: re-test by paging and checking whether any `github/*` repo appears. If exclusions work, owner partitioning becomes much simpler.

**Search limitations to add to 3.1.**
- The docs say "You must always include at least one search term when searching source code" [docs].
- Legacy code search also skips repos with more than about 500k files and repos without activity in about a year [recalled; worth re-checking because it drives drop-out logic].

**GraphQL throughput (table row in 3.1) is overstated by more than 10×.** See topic 3.

### 2.2 Additional queries and partition axes

| New ID | Query | Hits (2026-10-22) | Role |
|---|---|---|---|
| M-ROOT2 | `path:/ filename:marketplace.json plugins owner` | 399 [verified] | replaces M-ROOT |
| P-ROOT2 | `path:/ filename:plugin.json` plus one content term per slice (`skills`, `agents`, `hooks`, `mcpServers`) | untested | replaces the noisy P-ROOT |
| S-SET-CL | `path:.claude filename:settings.json extraKnownMarketplaces` (and `enabledPlugins`) | 4,104 [verified] | consumer-side pointer, read by VS Code |
| S-VSC | `path:.vscode filename:settings.json "chat.plugins.marketplaces"` | 19 [verified] | consumer-side pointer |
| S-README | `"copilot plugin marketplace add" extension:md`; also `"copilot plugin install"`, `"/plugin marketplace add"` | 4,632 for the first [verified] | text pointer to marketplaces |
| R-README | repo search `"marketplace.json" in:readme created:>DATE` and `in:readme "plugin marketplace add" pushed:>DATE` | untested | **date-filterable** incremental vector (repo search supports `created:`/`pushed:`; `in:readme` [recalled]) |

Other partition axes, beyond `size:`:
- **Content-term complements:** `"$schema"` vs `NOT "$schema"`, and `"source": "github"`-style terms. Legacy search supports `NOT` [recalled].
- **`extension:json`** vs none.
- **Owner partitioning** if `-user:` is confirmed.

Two practical details:
- Use the `application/vnd.github.text-match+json` media type so search results carry matched fragments [recalled]. S-README and S-SET can then pull `owner/repo` strings without fetching any files.
- Persist each `(query, slice, page)` cursor, so a 10/min sweep interrupted by the 6-hour Actions job limit resumes in the next run [recalled limit].

### 2.3 Incremental design: split discovery from refresh

The plan re-sweeps search nightly to refresh known repos. That is backwards.

- **Refresh known repos** directly by GraphQL, gated on head-commit oid (topic 3). This needs no code search at all, so it is not hurt by index lag, deprecated sort, or inactive repos dropping out of the index.
- **Discover new repos** with:
  - full Tier A/B search sweeps (about 30–60 requests, so nightly is fine);
  - R-README and topic searches with `created:>yesterday`;
  - graph expansion from changed manifests and settings files;
  - best-effort `sort=indexed` pages for Tier C;
  - a weekly or monthly full Tier C sweep.
- **Optionally use GH Archive** `CreateEvent`/`ForkEvent` to pick up new repos and forks whose names match `plugin|marketplace|skills|copilot`. These become cheap candidates for root-tree verification. Note that GitHub trimmed `PushEvent` payloads in 2025 [recalled; check before relying on it].

### 2.4 Completeness checks

Sourcegraph is shown to be a sample (83 against 884), so it is a weak check. Better options:

- **A golden recall set** checked on every run: the 66 external repos in awesome-copilot [verified count], the 7 in copilot-plugins [verified], the user's own repos, and the documented examples. Alert if recall drops below 100%.
- **Capture–recapture.** Treat code search and the graph-expansion/README vectors as two independent "captures" and compute a Lincoln–Petersen estimate of the true population per tier. Publish it as "estimated coverage" in the UI header.
- **A slice-closure check:** a slice is complete only when its last page is short. This is already in the plan; keep it.

---

## 3. Metadata (section 4)

### 3.1 The GraphQL batch design (3.4 and 4.1) does not work as written

I measured it on 2026-10-22 against 100 repos from `topic:claude-code-plugin` [verified]:

| Batch | Contents per repo | Result |
|---|---|---|
| 100 repos | repo fields + root tree entries + topics + 8 `object(HEAD:path)` blobs with `text` | **HTTP 502 after ~10.9 s** |
| 50 repos | same | **HTTP 502 after ~10.8 s** |
| 25 repos | same | **HTTP 502 after ~10.8 s** |
| 50 repos | repo fields + 8 blobs, no `text`, no tree entries | **HTTP 502** |
| 10 repos | full (8 blobs with text) | OK, 5.3 s, cost 1 |
| 50 repos | repo fields + root tree entries only | OK, **5.4 s**, cost 1 |
| 50 repos | root tree + 2 directory lookups (`.claude-plugin` entries with blob text, `.github/plugin` entries) | OK but **9.5 s**, at the timeout edge |

The cost is driven by the number of git object lookups per query (8 × 50 = 400), not by points. `rateLimit.cost` stayed at 1 for successful queries. However, the two failed queries in my first run appear to have used about 24 points, judging by `remaining` [verified, approximate]. So timeouts are not free.

The table's figure of "~250k repo-verifications/hour" assumes 1 point per 50–100 repos. Measured: at most about 50 repos per 5.5 s for a tree-only pass, roughly 30k repos/hour serial. GitHub also applies GraphQL secondary limits (points per minute and CPU time per minute) [recalled].

Change: replace 3.4 with a **two-stage verification**.

1. **V1 gate (50 repos per query, about 5 s).**
   - Fetch: `id` (node ID), `databaseId`, `nameWithOwner`, `isFork`, `parent`, `templateRepository`, `isArchived`, `archivedAt`, `isEmpty`, `isLocked`, `isDisabled`, `stargazerCount`, `forkCount`, `pushedAt`, `defaultBranchRef{name target{oid committedDate tree{oid entries{name type oid}}}}`.
   - If the head `oid` equals the stored one, stop for that repo.
   - The root entry oids also show which manifest directories exist and whether they changed.
2. **V2 fetch (about 10–20 repos per query, only for changed repos).**
   - Look up only the manifest directories that exist (`HEAD:.github/plugin`, `HEAD:.claude-plugin`, `HEAD:.plugin`, root files), then fetch blob `text` only for oids not already stored.
   - Store blobs content-addressed (3.4 below), so the 5,000 awesome-copilot forks cost one blob fetch, not 5,000.

Run 2–3 queries concurrently with backoff on 502/403. Calibrate the batch size dynamically: halve it on timeout, grow it slowly on success.

Optional fallback for blob text: `raw.githubusercontent.com/<owner>/<repo>/<sha>/<path>` with the immutable commit SHA. It is cacheable and does not use API points, but it is CDN rate-limited by IP [recalled].

### 3.2 Fields to add

- **`templateRepository{nameWithOwner}`**: exists on `Repository` [verified, introspection]. This is a definitive "generated from template" edge for de-dup.
- **`id` (GraphQL node ID)**: re-verify known repos with `nodes(ids:[...])`, which is rename- and transfer-proof [recalled behaviour]. Keep `databaseId` as the primary key.
- **`archivedAt`, `isEmpty`, `isLocked`**: exist [verified, introspection].
- **Head commit `committedDate`**: a better "last updated" for the default branch than `pushedAt`, which changes on any branch push.
- **`effective_manifest_path`, `shadowed_manifests[]`, `surfaces[]`, `executes_code`**: see topic 1.
- **Reverse-reference counts**: `referenced_by_marketplaces` (how many indexed marketplaces list this repo as a `source`) and `referenced_by_settings` (how many settings files name it). These are free by-products of graph expansion and the closest thing to an install-count signal. This settles open question 5: yes, keep "adopters".
- **Manifest-level fields**: `author.name`, `homepage`, `repository`, `license`, `keywords`, `category`, `tags`, `strict`, entry-level component paths.

### 3.3 Fields to drop or defer

- **`history.totalCount`**: can be slow on large repos and adds risk of the 10 s timeout [recalled]. Compute it only for canonical repos in the expensive pass, or drop it.
- **`issues(states:OPEN).totalCount`, `watchers.totalCount`, `diskUsage`**: low value for this product. Defer them.
- **README**: `HEAD:README.md` misses `readme.md`, `README.rst` and `docs/README.md`.
  - Pick the README name from the root tree entries in V1, then fetch the text only for Tier A/B and above a star threshold.
  - Keep `readme_oid` (free from tree entries) for de-dup.
- **`forkCount` meaning**: it counts direct forks. REST `network_count` counts the whole network [recalled; equal for awesome-copilot today, verified]. Fine as is, but label it accordingly.

### 3.4 Batching and storage of blobs

Change: add a `blob(oid PK, byte_size, text, parsed_json, parse_error)` table. Have `marker_hit`, `repo_manifest` and `plugin` reference blob oids. This deduplicates fork and clone content, makes "has the manifest changed" a simple oid comparison, and keeps re-verification cheap.

---

## 4. De-duplication (section 5)

### 4.1 Missing signals

- **`templateRepository` edge** (definitive) [verified field exists]. It replaces the heuristic "from_template" logic in 5.2. Template children should form a *template family* and are not clones of each other. The plan's intent is right; GraphQL just gives the edge directly.
- **Subtree oids per plugin directory.**
  - The tree entries returned by V1/V2 include `oid` for each directory [verified].
  - The same `plugins/<x>` tree oid in two repos means a byte-identical vendored plugin, even when the repo trees differ.
  - Add this as a strong *plugin-level* signal (5.2, "Plugin-level duplicates"). It is better than "name+version", which collides across unrelated plugins named `my-plugin` at `1.0.0`.
- **`SKILL.md` blob oid sets** per plugin, as a medium signal for partially copied plugins.

### 4.2 Over-merge risks

- **Boilerplate blobs.**
  - README oid (signal 4) and manifest oid (signal 3) are listed as "strong" and feed union-find directly.
  - Scaffolded `plugin.json` files (`{"name":"my-plugin"}`), template READMEs, and generator-produced marketplaces are byte-identical across unrelated authors.
  - Change: add a frequency and size guard. An oid seen in more than N distinct owners whose byte size is below roughly 300 bytes is "boilerplate" and gives no evidence. Store blob-owner frequency in the `blob` table.
- **Transitive chaining.**
  - Union-find over strong edges chains A–B (README) and B–C (manifest) into A–B–C even when A and C share nothing.
  - Change: use union-find only for definitive edges (fork, template, identical root tree). Attach strong and medium evidence to a cluster only if it links to the cluster's canonical (star clustering), or require two independent strong edges for non-definitive joins.
- **Divergent forks.**
  - The fork edge is "definitive", so a fork that became its own project would be merged into the original and hidden. Signs of such a fork: its own marketplace `name`, many own commits, more stars, the original archived.
  - Change: keep the fork edge as provenance. Split the fork into its own cluster when its manifest oid differs **and** (it has ≥X own stars **or** its marketplace name differs **or** it is listed by a seed marketplace). Show "fork of Y" in the detail panel.
- **Identical root trees of near-empty repos.** Repos containing only a template README and LICENSE would match signal 2. Apply the same boilerplate guard to the root tree (minimum entry count or size), or require a manifest blob in the shared tree.
- **Distribution is not duplication.** A marketplace listing a `source` repo should never merge into that repo. The plan implies this; state it explicitly as a non-edge.

### 4.3 Under-merge risks

- Clones that rename the marketplace or move plugins into a different path are missed by signals 2, 3 and 5, but caught by subtree oids (4.1).
- History-rewritten clones with one edited file are missed by 2 and 7, but caught by subtree oids and `SKILL.md` oid sets.
- Unindexed forks (about 92% of awesome-copilot forks, per 2.1) are invisible. That is acceptable, because they are counted through `forkCount`, but say so in the UI.

### 4.4 Canonical tie-breakers (5.3)

- **"Fork network root".** GraphQL has no `source` field; only `parent` [verified: introspection]. REST `source` exists on fork repos [recalled]. Walk `parent` up to 2–3 levels in GraphQL, or call REST once per fork-cluster root.
- **Liveness over the root.** Rule 1 should yield when the root is `gone`, `demarked`, archived or disabled and some member is active with a valid manifest. Add "has a valid effective manifest and is not archived" as rule 0.
- **Seed pointer.** Move rule 3 above rule 2. When awesome-copilot points at a fork, that is GitHub's own judgement of the maintained copy.
- **Tier interaction (important).**
  - If the canonical is Tier C but a member carries `.github/plugin` (Tier A), the default A+B view hides the whole cluster.
  - Change: compute `cluster_tiers = union over members`, filter on cluster tiers, and badge "a member has a Copilot-native manifest".

---

## 5. Storage and refresh (section 6)

- **Drop-out (6, "Drop-out rule").**
  - Do not trigger on "missing from two full sweeps". Search presence is noisy: index lag, inactivity eviction, approximate totals, and deprecated `sort`.
  - Change: drive status from direct V1 verification of the whole known set, on a cadence by tier and popularity: Tier A/B nightly, Tier C every 3–7 days. At about 30k repos/hour, the gated V1 on 50k repos is a 1–2 hour job; split it across nights.
  - Transitions:
    - `active` → `demarked` when the effective manifest disappears at HEAD;
    - → `gone` when the node returns null or `NOT_FOUND`;
    - → `renamed` when `nameWithOwner` changes for the same `databaseId`;
    - plus an `inaccessible` state for disabled, DMCA or made-private repos.
  - Keep `last_seen_in_search` as a diagnostic only.
- **Schema additions.**
  - `blob` (content-addressed, see 3.4).
  - `repo_state(repo_id, head_oid, root_tree_oid, verified_at, etag)`.
  - `manifest_history(repo_id, path, blob_oid, first_seen, last_seen)` to track manifest changes.
  - `plugin_ref(marketplace_repo_id, entry_name, source_kind, source_host, target_repo_id, target_path, ref, sha)`, separate from `plugin`, so that one plugin with many distributors is explicit.
  - A unique key on `marker_hit(repo_id, marker_id, path)`.
  - A `schema_version` table for migrations.
- **`repo_daily` will not stay small.** 50k rows/day is about 18M rows/year, several hundred MB in SQLite. Change: write a row only when stars or forks change, or snapshot Tier C weekly and Tier A/B daily.
- **Committing SQLite to git.** A nightly binary commit of a growing SQLite file bloats the data branch quickly. Change: commit diffable NDJSON snapshots (or one Parquet file per day as a release asset), rebuild SQLite in CI, and keep the working DB in Actions cache.
- **Scheduled workflows.** GitHub disables scheduled workflows in public repos after 60 days without repository activity [recalled]. The nightly data commit probably counts as activity, but add a failure alert anyway (Phase 5 already mentions alerts; move it to Phase 1).

---

## 6. UI/UX (section 7)

- **Primary entity (open question 2).**
  - Users look for *a plugin or skill that does X*, not for a repository.
  - A plugin list derived from marketplace entries costs no extra API calls, because the entries are already parsed.
  - Change: ship two tabs in Phase 3, **Repositories** and **Plugins**. The plugin list shows name, description, distributors and source repo. Skills stay in Phase 4.
- **Filters (7.2): add the following.**
  - "installable on surface" (CLI / VS Code / app / cloud agent), from the support matrix;
  - "executes code" (hooks / MCP / LSP / extensions);
  - "Copilot-specific components";
  - "listed by awesome-copilot / copilot-plugins";
  - "marketplace vs single plugin";
  - "referenced by N marketplaces or settings files";
  - "shadowed or misplaced manifest";
  - owner with type-ahead.
  - Show facet counts next to each filter value, and make chart marks act as filters (click a bar to filter).
- **Default sort.**
  - Stars descending with clusters collapsed is fine for v1.
  - Once snapshots exist, add a "trending" sort (7-day star delta) and an "adoption" sort (reverse references).
- **Charts.**
  - "Repos first seen per week" will spike on the first scan day and measure the crawler rather than the ecosystem. Plot `createdAt` (or the manifest's first-commit date, later) by week, stacked by tier.
  - Cut v1 to three charts: growth, format split, top owners.
  - Show the coverage estimate (2.4) and the fork-indexing caveat in an "About the data" panel.
- **Detail panel.**
  - Build install snippets from the **manifest's marketplace `name`**, not the repo name, plus the effective path. For forks of awesome-copilot the manifest name is still `awesome-copilot`, which collides with the built-in marketplace; warn about that.
  - Add copy buttons, a "fork of / template of" line, reverse references ("listed in"), and execution-risk badges.
  - Sanitise URLs (allow only `https:`, never `javascript:`), cap string lengths, and strip bidi control characters from third-party text.
- **Search and performance at 50k rows.**
  - Build the MiniSearch index offline and ship it serialised (`toJSON`/`loadJSON`). Run filtering and search in a Web Worker.
  - Export rows column-oriented, with dictionary-encoded owner, language and license; expect 2–3× smaller files than row JSON.
  - If Tier C grows past about 100k rows or plugin/skill rows reach hundreds of thousands, switch to DuckDB-WASM over Parquet with HTTP range requests, which is still a static site, before considering a server.
  - TanStack Table plus TanStack Virtual is fine.
- **Static vs server.** I agree with static on GitHub Pages. Note the Pages limits (100 MB per file, about 1 GB site, soft bandwidth cap [recalled]); they are comfortable at this size.
- **Exports.** Include a cluster-members export and a link "open this marker query in GitHub code search" for transparency.
- **Mobile.** Show a card layout under about 640 px. A 15-column table is unusable on a phone.

---

## 7. Architecture, risks, open questions and phasing

**Architecture (section 8).**
- **Token.** The `GITHUB_TOKEN` question is real. Even if it is accepted, it has a lower REST budget than a PAT (about 1,000 requests/hour per repo [recalled]). Plan on a fine-grained PAT, or a GitHub App installation token with its own budget, from the start.
- **Actions job limit.** It is 6 hours [recalled]. Make cursor persistence explicit: store it in the data branch or the cache, alongside resumable paging.
- **Rate limiter.** Add GraphQL secondary-limit awareness (points per minute, concurrency) and adaptive batch sizing (3.1).
- **Testing.** Add classifier fixtures (real manifests: valid, invalid, shadowed, nested, suffix-matched filenames), a golden recall set, and snapshot tests of the clustering on a frozen sample.

**Risks (section 9): add these.**
- The deprecation of `sort=indexed`.
- The GraphQL timeout ceiling, and timeouts consuming points.
- Boilerplate-blob over-merge.
- Manifest shadowing.
- Doc inconsistency about default marketplaces and per-surface support.
- PII in manifests.
- Hostile content (huge JSON, deeply nested JSON, bidi characters, `javascript:` URLs).
- Scheduled-workflow auto-disable.

**Open questions (section 10): add these.**
- Which surface's precedence defines "effective manifest" (CLI documented; VS Code not)?
- How does the cloud agent consume plugins?
- Does VS Code read `.plugin/` ("legacy OpenPlugin")?
- Data retention and PII policy.
- Star-snapshot cadence per tier.
- Is Tier C labelled "Copilot-installable" or hidden entirely?

**Answers I would give to the existing open questions.**
- Q1: incremental Tier C plus a monthly full sweep, with direct V1 re-verification of known repos.
- Q2: both entities in Phase 3, as two tabs (6 above).
- Q4: test it in Phase 1 with a one-line workflow.
- Q5: yes, and use the data as a ranking signal.
- Q6: keep Cursor and Codex as attributes only (they are free by-products), and drop npm/PyPI counts.
- Q7: definitive edges only by default; strong edges only with the boilerplate guard; audit 50 clusters.

**Phasing (section 11).**
- **Phase 1:**
  - add a half-day spike to confirm `path:/` anchoring, `-user:` exclusion, exact-filename behaviour, `sort=indexed` status and GraphQL batch calibration;
  - include the golden recall set and the scan-failure alert;
  - the exit criterion should include "100% recall on the golden set".
- **Phase 2:** add `templateRepository`, subtree-oid signals and the boilerplate guard. Move the deny-list here from Phase 5.
- **Phase 3:** add the plugin tab from marketplace entries.
- **Phase 4:** unchanged, except that "incremental `sort=indexed` runs" become "best-effort, with the date-filtered repo-search fallback".

---

## 8. Prioritised top-10 changes

1. **[must]** Rewrite 3.4/4.1 as two-stage verification: a V1 root-tree gate at about 50 repos per query, skipped when the head oid is unchanged, then V2 targeted blob fetches at 10–20 repos per query, with adaptive batch size. The current design returns HTTP 502 at 25, 50 and 100 repos (verified), so the "250k/hour" figure is wrong.
2. **[must]** Drive refresh and drop-out from direct GraphQL re-verification of known repos (via `nodes(ids:)` or `databaseId`), not from search presence. Search should only discover; `sort=indexed` is "closing down" per the REST docs (verified).
3. **[must]** Fix the Agent Plugins rules in 2.1: `$schema` and `name` are both required, the name rules differ from legacy, and unknown fields are warnings, not rejection. Add `strict`, `category`, `tags` and the entry-level component fields, and build the plugin inventory from marketplace entries first.
4. **[must]** Add an over-merge guard to 5.2: union-find only on definitive edges (fork, `templateRepository`, non-trivial identical root tree), boilerplate suppression for small or high-frequency blobs, and a divergent-fork split rule.
5. **[must]** Compute cluster tier as the union over members, so a Tier C canonical with a Tier A fork still appears in the default view. Add rule 0, "active with a valid effective manifest", ahead of "fork network root".
6. **[should]** Add the discovery vectors I verified today: `.claude/settings.json extraKnownMarketplaces` (4,104), README "copilot plugin marketplace add" (4,632), `.vscode` `chat.plugins.marketplaces` (19). Replace M-ROOT with `path:/ filename:marketplace.json plugins owner` (399, root-only).
7. **[should]** Record `effective_manifest_path` (first existing path in CLI precedence) and `shadowed_manifests[]`, exact-basename checks (filename search matched `.agent-marketplace.json`), `surfaces[]` and `executes_code`. Expose them as filters and badges.
8. **[should]** Add the `templateRepository` edge (exists on GraphQL `Repository`, verified) and per-plugin subtree oids as de-dup signals. Store blobs content-addressed so 5,191 awesome-copilot forks share one manifest row.
9. **[should]** Ship a Plugins tab in Phase 3, built from already-parsed marketplace entries. Add reverse-reference counts ("listed by N marketplaces, enabled in N repos") as a ranking and filter signal.
10. **[nice]** Replace Sourcegraph as the completeness check with a golden recall set (the 66 + 7 seed-referenced repos) and a capture–recapture coverage estimate shown in the UI. Commit NDJSON or Parquet snapshots rather than a binary SQLite file, and store `repo_daily` only on change.
