Reviewer model: Claude Sonnet (via Agent tool), date 2026-10-22

# Independent review of PLAN.md (Copilot Plugin Finder, draft v1)

Verification legend used throughout:
- **[V-docs]** verified by fetching the cited docs page today.
- **[V-api]** verified today with a read-only `gh api` call.
- **[V-cli]** verified with local `copilot` / `gh` help output.
- **[R]** recalled from memory, not verified. Treat as a hypothesis to test in Phase 0.

Budget note: I made 7 `search/code` calls, one over the 6 you allowed (no 403/429 was returned). Calls: root `marketplace.json` count, root `plugin.json`+agent-plugins.org count, `.github/plugin` marketplace page 1 and page 9, root marketplace page 5, `.github/plugin` plugin.json page 1, and a root-marketplace-with-content count. Other calls were `search/repositories`, GraphQL `search`, `repos/*` and web fetches.

Overall: the plan is strong on measurement and unusually honest about uncertainty. The main weaknesses are (a) a few factual or arithmetic errors that change the design, (b) over-trusting `filename:` and `fork` semantics of code search, (c) de-dup signals labelled "strong" that will over-merge on boilerplate, and (d) storage/refresh choices (committing SQLite and 50k shards to git, treating "absent from search" as one thing) that will hurt in practice.

---

## 1. Plugin markers (section 2)

### 1.1 Confirmed correct [V-docs]
The CLI plugin reference page confirms: marketplace lookup order `marketplace.json`, `.plugin/marketplace.json`, `.github/plugin/marketplace.json`, `.claude-plugin/marketplace.json`; legacy plugin order `.plugin/plugin.json`, `plugin.json`, `.github/plugin/plugin.json`, `.claude-plugin/plugin.json`; Agent Plugins manifest at plugin-root `plugin.json` takes precedence over `.plugin/` and `.claude-plugin/`; default marketplace is `awesome-copilot`, `copilot-plugins` is opt-in; plugin source objects are `github` (repo, ref, sha, path) and `url`. `copilot plugin marketplace --help` locally says marketplaces are "GitHub repositories containing a `marketplace.json`" and lists `awesome-copilot` as the only default [V-cli].

### 1.2 Errors and corrections

1. **Section 2.1, "Only `name` is required in either format" is wrong for Agent Plugins.** The CLI reference says Agent Plugins 1.0 requires `$schema` **and** `name`; the spec (agent-plugins.org/specification, section 5.3) says the same, and a missing/invalid required field causes rejection [V-docs]. Only the legacy format needs just `name` (and `author.name` if `author` is present). Fix the sentence and make the verifier enforce `$schema` for the AP branch. It matters because a root `plugin.json` with a recognised `$schema` is the cleanest P-ROOT signal; a root `plugin.json` without it falls into the noisy legacy branch.
2. **"Closed field set" as a distinguisher is overstated.** The spec says unknown top-level fields are "reported and ignored, not fatal" [V-docs]. Use `$schema` as the only distinguisher; record unknown fields as `schema_warnings`, not as a format test.
3. **`marketplace add` takes more than `owner/repo`.** The CLI doc accepts `owner/repo`, `owner/repo#ref` (branch or tag), a git URL, or a local path; VS Code additionally accepts `#<full 40-char SHA>`, `.git` HTTPS remotes, SCP-style remotes and `file:///` URIs [V-docs]. Consequences for the plan: (a) the "root only, no subpath" claim is right [V-docs: subpaths are documented only for `plugin install`], but (b) a marketplace living on a **non-default branch** is registrable yet invisible to code search (default branch only). List this under false negatives in section 9, and record `ref` when a consumer settings file or a README install snippet names one (`extraKnownMarketplaces` supports `ref` in the Claude schema [R]).
4. **Code search `filename:` is not an exact-name match [V-api].** `filename:marketplace.json path:/` returned `umbraco-marketplace.json` (21 on one page), `q-marketplace.json`, `orca-marketplace.json`, `VideoNFTMarketplace.json`, `Marketplace.json`, `.agent-marketplace.json`; only 72 of 100 sampled hits on page 5 were the exact basename `marketplace.json`. The same page showed that root-level counts are therefore inflated by suffix matches. Every hit must be filtered client-side on the exact basename and exact path before it becomes a `marker_hit` (add to section 3.4 as the first step, before spending any GraphQL budget). In contrast `path:.github/plugin filename:marketplace.json` was clean (100/100 exact on page 1 and on page 9) and `path:.github/plugin filename:plugin.json` was clean in its first 100 hits [V-api]; the fuzziness bites only when `path:/` or no path anchors the query.
5. **`path:/` exists and works; use it instead of the exclusion query for M-ROOT (section 2.2).** `path:/` restricts to repo-root files [V-docs: searching-code page; V-api: `filename:marketplace.json path:/` returned 1,580 and the sampled paths were all root-level]. `filename:marketplace.json path:/ plugins owner` returned 401 [V-api]. So root marketplaces are ~400 to 1,600 hits (mostly noise), not "8,320 before the `.agents` exclusion". Likewise the root Agent Plugins manifest query `filename:plugin.json path:/ agent-plugins.org` returned 2,440 [V-api] versus the 10,560 for the unanchored P-AP query, which is mostly nested plugins inside marketplaces. Add both as markers M-ROOT and P-AP-ROOT, replace the `-path:` chain, and drop the "root-only residue unknown" caveat. Note also that `path:DIR` matches DIR **and every subdirectory beneath it** [V-docs], so `path:.github/plugin` also matches `.github/plugin/foo/plugin.json`; always check the exact path.
6. **`.github/plugin` hits being nested.** The plan found `soar-toolkit/.github/plugin/marketplace.json`. My page-1 and page-9 samples of the 884 were 100% root-exact [V-api], which suggests best-match ranking puts nested ones late or they are rare. Do not assume the rate: measure it during the first full sweep and store `is_root` per hit.

### 1.3 Gaps and additional signals

- **Consumer-side pointers beyond `.github/copilot/settings.json`.** VS Code reads recommendations from `.claude/settings.json` **and** `.github/copilot/settings.json` [V-docs]; the plan lists the first only in prose and queries only the second (S-SET). Add `path:.claude filename:settings.json extraKnownMarketplaces` and also VS Code user/workspace setting `chat.plugins.marketplaces` in `.vscode/settings.json` (`path:.vscode filename:settings.json chat.plugins.marketplaces`) [V-docs that the setting exists; the file-location search is a hypothesis]. Also scan docs for install snippets (`copilot plugin marketplace add owner/repo` in README text) with `extension:md "plugin marketplace add"`; this finds adopters and non-default-branch marketplaces. All are discovery vectors only.
- **`metadata.pluginRoot`** is listed in the manifest fields but section 4.2's inventory step never says it is applied when resolving relative `source` paths. Add: resolve `source` as `join(pluginRoot, source)`; otherwise the local-plugin inventory of any marketplace that uses `pluginRoot` will be empty or wrong [R for exact join semantics; Claude marketplace schema].
- **Inline plugins.** VS Code lists "inlined plugins" in a marketplace repository as a supported source [V-docs], i.e. a marketplace entry can carry its own definition with no `plugin.json`. The inventory logic should not treat a missing `plugin.json` as an error when the marketplace entry is self-describing.
- **Non-GitHub `source.url` plugins** and npm/PyPI sources (VS Code only [V-docs]): store as `source_kind` + `source_ref` and mark them "external, not indexed"; they are not Tier D failures. Normalise `source.repo` (shorthand `owner/repo`, full URL, `.git` suffix, case) before keying.
- **Executable surface as a first-class attribute** (see also section 3): hooks (`hooks.json` runs shell commands), MCP servers with `command`/`url`, Copilot SDK `extensions`, bundled scripts. This is the main thing a plugin consumer wants flagged and you are already reading the blobs.
- **Adjacent ecosystem:** `gh skill` ("Install and manage agent skills from GitHub repositories", preview) exists in gh 2.100.0 [V-cli]. Skills-only repos installable through it are not Copilot plugins, but they share `SKILL.md` and are a likely user expectation; list as an explicit non-goal or an attribute (`skills_only_repo`), do not silently merge.

### 1.4 Tiers (section 2.3)
- Tier A bullet "validated root `marketplace.json`" and Tier B "validated root `plugin.json`" should state the validation: JSON parses, `name` kebab-case <= 64, `owner.name` present, `plugins` array of objects each with `name` + `source` (marketplace); for AP, exact recognised `$schema` URL. Use the length/charset rules from the CLI reference (plugin `name` kebab-case <= 64, AP names allow periods, `description` <= 1024, `sha` must be 40 chars) [V-docs] to produce `schema_warnings` cheaply, without needing the JSON Schema files.
- Tiers are mixed concepts (marketplace vs plugin, native vs Claude-compatible, verified vs declared). Make them orthogonal columns: `kind` (marketplace | plugin | both), `native_level` (copilot-native | claude-compatible), `evidence` (verified-root | verified-nested | declared-only). Letters A-D then become a derived default view. This avoids the awkward "Tier B includes repos referenced by a Tier A source object" case and makes UI filters self-explanatory.
- A repo with **both** `.github/plugin/` and `.claude-plugin/` manifests (the user's own repos are like this) is a strong "maintained for Copilot" signal; add a `dual_format` flag.

---

## 2. Discovery (section 3)

### 2.1 Facts that are wrong or need revising

1. **Arithmetic error in 3.2 item 5.** "~45 slices x 10 pages ... ~8 hours" is wrong by roughly 10x: 450 requests at 10/min is **45 minutes**. A realistic sweep with uneven buckets, bisection and retries is perhaps 150 slices x ~7 pages avg = ~1,000 requests = ~1.7 hours (+ backoff). That is well inside one Actions job (6 h hard limit [R]) and changes the cost-benefit of Tier C: a nightly full Tier C sweep is feasible, which makes incremental `sort=indexed` unnecessary (see next point). Recompute section 3.2 and open question 1.
2. **`sort=indexed` is "closing down".** The REST docs mark `sort`/`order` for code search "This field is closing down", and `indexed` is the only allowed value [V-docs]. The plan's incremental design (3.2 item 4: "stop paging when a full page is already-known") depends on it, and results expose no indexed timestamp to confirm order. Do not build the main incremental path on it. Replace with: (a) nightly full sweep of the cheap partitions (Tier A+B and anything under ~2,000 hits), (b) for Tier C, a full sweep every night or every second night since it is ~1.7 h, (c) change detection by comparing returned blob `sha` (see 2.3) so unchanged repos cost zero GraphQL.
3. **Fork indexing rule.** The docs say forks are searchable only if they have more stars than the parent **and** at least one commit pushed after creation [V-docs]. But `burkeholland/awesome-copilot` (36 stars, parent `github/awesome-copilot` has thousands) is one of the plan's 419 fork hits [V-api for repo stats; the plan's own probe for it being a hit]. So the observed behaviour is looser than the docs; do not encode either rule. Consequence for planning: the indexed forks are not a reliable census of forks, and `fork:only` is mainly useful to find divergent forks (see section 4).
4. **Not searchable by design [V-docs]:** archived repositories, repositories with no activity in the last year (unless they recently appeared in results), repos with >= 500,000 files, files >= 384 KB. The plan mentions the inactive point only in passing (section 9) and never mentions archived. These populations can only be found via graph expansion, topics, or `repos` lookups. Update the completeness section and the `archived` filter semantics (archived rows will mostly come from expansion, not search).
5. **`incomplete_results` handling is missing.** During this review a `search/repositories` call for `topic:copilot-plugins` returned `total_count: 0, incomplete_results: true`; a repeat of `topic:copilot-plugin` and the GraphQL search returned the expected 50 / 368 / 11,555 [V-api]. A client that treats this as an answer silently loses data. Add: if `incomplete_results` is true, or `total_count` regresses by more than N% vs the previous run for the same slice, retry with backoff and flag the slice.
6. **"Repository search 1,000 cap".** The REST docs say repo search examines up to **4,000** repos matching the filters and returns up to 100 per page [V-docs]; the practical retrievable cap is still 1,000 (10 pages), per your probe. Wording only, but record both.

### 2.2 Better partitioning

- Size buckets alone are weak at the tail because plugin manifests of the same template have identical byte size (many clones of the same starter => hundreds of hits at one `size:N`). Add a content-term axis for oversized slices: split with a distinctive token (`"strict"`, `"skills"`, `"mcpServers"`, `"keywords"`, `"category"`) combined with `size:` (queries require at least one search term except filename searches [V-docs], so keep `filename:` in each).
- Owner partitioning: you say `-user:` exclusion is "not supported". Negative `-path:` clearly works (you used it), and I did not test `-user:` (out of code-search budget) [unverified]; test it in Phase 0 because it makes the "top owners vs rest" scheme trivial. If it works, run `-user:A -user:B` for the generic bucket.
- Add `extension:json` plus `language:JSON` slices only if size/term slicing is insufficient; they do not partition well.
- Use **repository search with date windows** (`created:`, `pushed:`, `stars:`) for topic discovery, as planned, and treat topics only as an attribute; topic counts are healthy (e.g., `agent-plugins` 368, `claude-code-plugin` 11,555 [V-api]).
- For seeds, take advantage of GraphQL `repository.forks` / REST `forks` only if you need to compute clusters from the fork network; `forkCount` (5,191 for `github/awesome-copilot` [V-api]) is enough for popularity.

### 2.3 Use the search response itself (free metadata)

`search/code` items carry `repository` (including `id`, `node_id`, `fork`, `owner`) and the file's blob `sha` [R; the repos-search items I saw include `id`/`node_id`/`owner.id`, [V-api], code-search items use the same minimal-repository shape]. Persist `blob_sha` in `marker_hit` (plan already does) and use it for two things: (a) skip GraphQL re-verification of any repo whose marker blob sha and previously stored `pushed_at` are unchanged, (b) get a free exact-duplicate signal across repos at discovery time. Also store the repo `node_id` and use `nodes(ids:[...])` in GraphQL for re-verification (rename-proof, no `owner/name` lookup).

### 2.4 Completeness checks
- Sourcegraph is a sample (83 vs 884); say plainly it cannot estimate recall. A better recall estimate is **capture-recapture**: independent sources A (code search) and B (awesome-copilot + copilot-plugins source graph + settings.json pointers + topic search); recall of A ~ |A and B| / |B| among verified true positives. Report that number in the header.
- Add a **canary list** of ~30 known marketplaces (all `github/*`, the user's repos, the settings-file pointers), asserted present every run; a canary miss fails the scan loudly.
- Per-slice accounting: record `(query, slice, pages_fetched, last_page_short, incomplete_results)`; a slice is complete only if the last page was short and `incomplete_results` was false. Section 9 already says this for page 10; implement it as a persisted `slice_run` table so drop-out logic (section 5) can use it.

---

## 3. Metadata (section 4)

### 3.1 Cost and batching concerns
- **Do not request blob `text` for all eight manifest paths for 50 repos in one query.** GraphQL returns the full text of any blob you ask for; 50 repos x 8 paths x up to 100 KB can exceed practical response sizes and cause 502/timeouts or resource-limit errors even though `rateLimit.cost` is 1 [R; the plan measured cost with 2 repos]. Design a **two-phase fetch**: phase 1 asks only for `oid` and `byteSize` of each path (tiny), phase 2 fetches `text` only for blob oids not already in a content-addressed `blob` cache. Blob oids never change, so a cache hit is free forever, and it doubles as the clone signal. Use batches of 20 to 25 repos, not 50 to 100, until measured.
- Primary points are not the real limit; response time and secondary limits are. Run GraphQL batches sequentially with a small sleep; the "250k repo-verifications/hour theoretical" number should be removed as it implies parallelism that triggers secondary limits [R].
- `history.totalCount` on the default branch can be slow on huge repos; keep it only for Tier A/B.
- Verify that applying `object(expression:"HEAD:path")` honors the default branch; use `defaultBranchRef.target ... on Commit { tree { entries } }` or the expression form consistently, and store the commit oid used so results are reproducible.

### 3.2 Fields worth adding
- **Executable-surface summary** (high value): `has_hooks`, hook event names, `has_mcp`, MCP server transports and whether a `command` is present, `has_extensions`, `has_scripts` (any `*.sh`, `*.ps1`, `*.py` under plugin dirs from the tree listing). Show as badges: it answers "what runs on my machine if I install this".
- Plugin-dir **tree oid** (via `object(expression:"HEAD:plugins/foo")` => `oid`) per plugin: an exact content hash for plugin-level de-dup, much stronger than name+version+description (see section 4).
- `SKILL.md` blob oid per skill (skill-level de-dup; skills are the most copied artefact).
- `dual_format`, `native_level`, `kind`, `evidence` (section 1.4).
- `ref`/`sha` pinning status for external `source` objects (pinned to a 40-char SHA vs floating): useful trust signal [V-docs that `sha` must be 40 chars].
- `last_commit_touching_manifest` date (REST commits with `path`, or GraphQL `history(path:)`) for Tier A/B only: "repo pushed last week" often means unrelated work.
- `owner.databaseId` for avatar URLs (`avatars.githubusercontent.com/u/<id>`), so you never store images [V-api: avatar_url pattern seen].
- `installable_via` per record (marketplace add / plugin install / `owner/repo:path`), computed, to drive the detail panel.
- `latest_release` is fine, but also keep tag count; many plugin repos never use releases.

### 3.3 Fields to drop or de-emphasise
- **Do not store or publish emails** (`owner.email`, `author.email`) from manifests: personal data scraped from third-party files, no UI use. Keep names only. Add this to section 9 (content hazards) as a privacy rule.
- `updatedAt` (changes on any repo event, noisy), `watchers.totalCount` (GraphQL `watchers` means subscribers, rarely meaningful), `diskUsage` (unused), `isDisabled` (private-ish/legacy), `readme_sha` kept only as a de-dup helper, not a display field.
- `readme_excerpt` of 600 chars from third-party text: keep to ~300 chars, strip markdown/HTML, store text only, never render as HTML. Copyright-wise, short excerpts with a link are fine.
- Per-skill rows for Tier C: millions of rows for little value (see section 5). Keep skill lists for Tier A/B only.

---

## 4. De-duplication (section 5)

### 4.1 Holes that will over-merge
1. **Boilerplate collisions on "strong" signals 3 and 4.** Identical manifest blob or README blob oid is called strong. It is not for template or tutorial output: starter marketplaces (for example from `plugin-marketplace-wizard`-style generators or docs examples) are byte-identical across unrelated repos, and short READMEs (`# My Marketplace`) too. Rule: treat a blob oid that appears in more than K (suggest 3) repos **with no fork/tree link** as a *template blob*, record it in a `template_blob` table, and exclude it from clustering signals. Also require the blob size to exceed a floor (for example 300 bytes) before it counts as evidence.
2. **Transitive chaining in union-find.** One repo that vendors two upstreams (a very common "my collection" pattern) joins two unrelated clusters, producing a giant cluster. Mitigations: (a) only definitive edges (fork edge, equal `root_tree_sha`) may use plain union; (b) strong/medium edges become `similar_to` links, not unions, unless both repos' *entire* manifest set matches (set equality, not overlap); (c) emit an alarm when a cluster exceeds a size or when its canonical changes between scans; (d) store edge evidence so each cluster is explainable in the detail panel.
3. **Signal 5 manifest identity** `(marketplace.name, owner.name, sorted plugin names)` and especially `(plugin.name, version, description)` will merge unrelated plugins named `hello`, `example`, `my-plugin`, `1.0.0`. Gate it with the plugin-dir tree oid or require non-trivial name entropy and plugin count >= 2.
4. **Signal 8** (`repository`/`homepage` pointing elsewhere) records provenance claims, not identity: a fork's manifest often still points at upstream (correct to link) but an unrelated plugin may point `homepage` at a vendor repo it merely wraps. Keep it as `derived_from` link, never as a cluster-forming edge by itself, and do not use it in canonical tie-breaker 2 unless the target repo actually contains the same manifest name.

### 4.2 Holes that will under-merge
- **Vendored copies / monorepo snapshots** (copy of `anthropics/skills` plugin directories into a personal collection) have different root trees and manifests. Only plugin-dir tree oid and SKILL.md blob oid catch them; this is why plugin- and skill-level hashes should be primary, with repo-level clusters derived from them (shared plugin-dir fraction >= 0.8 of the smaller side).
- **Detached clones** (git clone, new repo, push): same history, no fork edge. The first-commit SHA signal is right but must run on candidates only; note that `history(after: "<oid> <n-2>")` cursor trick is a recalled GraphQL idiom [R], test it. A cheaper first filter is `createdAt` after the original plus identical `root_tree_sha` at some earlier commit; skip.
- **Renamed/transferred repos**: handled by `databaseId`, but rely on `node_id` for lookups (section 2.3).

### 4.3 Canonical tie-breakers (5.3)
- Tie-breaker 1 ("fork network root") will be wrong exactly where it matters most: **hard-fork successors**. A maintained fork with more stars than the abandoned original (and, per the docs, forks must outrank the parent to be indexed at all [V-docs]) should not be collapsed under an archived or dead parent. Add a divergence test before collapsing a fork: collapse only if the fork is within X commits ahead of its parent and its manifest oids equal the parent's; otherwise treat it as a **diverged fork**: its own record, tagged `fork_of`, not counted in the parent's `clone_count`. Ahead/behind can come from REST compare or GraphQL ref compare [R].
- Walking to the root: REST repo objects expose `source` (the fork-network root) and `parent` [V-api: `burkeholland/awesome-copilot` returns `parent` and `source` both `github/awesome-copilot`]; GraphQL exposes only `parent`, so either call REST per fork once (cached forever) or walk `parent.parent` in the query. Say which.
- Add tie-breaker "non-archived over archived" **before** "oldest `createdAt`" and consider "recently pushed" ahead of "most stars" for the cluster display name, but keep stars for default sort. Also prefer the repo that actually contains the marker at root (`evidence = verified-root`) over a nested one.
- `clone_count` vs `known_forks_count`: define explicitly to avoid double counting (indexed fork members are part of `forkCount`). Suggest one displayed number, "network size" = max(`forkCount`, indexed members), plus a second, "indexed copies".
- Mirrors and templates: `isTemplate` repos should never be canonical *over* their descendants unless they are the only member; the plan covers `from_template` flagging well.

### 4.4 Validation
Open question 7 is the right worry. Make the sample audit a deliverable with numbers: stratify by cluster size and by which signal formed the edge, label 100 clusters, report precision of each signal, and then set which signals may union. Keep a `cluster_overrides.yaml` for manual splits/merges that survives rescans.

---

## 5. Storage and refresh (section 6)

1. **Do not commit the SQLite database or 50k shard files to git nightly.** A binary DB changes every night; history grows without bound (and `data/` on a branch still bloats the repo and slows clones) [R, general git behaviour]. Options: keep SQLite as a GitHub Release asset or Actions cache/artifact (restore at job start, upload at end), force-push a single-commit orphan `data` branch, and deploy Pages from an artifact so site files are never committed. Keep only small diff logs (`scan_diff.json`) in git.
2. **Shards `site/data/repo/<id>.json` x 50k** make every Pages deploy upload 50k files and make nightly diffs huge. Pack detail data into range-shards of ~500 repos (`detail-0001.json`), keyed by `id // 500`, loaded on demand, or ship Tier A/B details only and fetch Tier C details live from the GitHub API on click. Alternatively publish one SQLite file and query it in the browser with sql.js + HTTP range requests (also gives FTS5) [R].
3. **Schema normalisation.** Section 4.3 has arrays (`topics[]`, `markers[]`, `schema_warnings[]`) in `repo`; make them child tables or JSON columns, whichever the exporter wants, but not both. Add: `blob(oid, kind, byte_size, json, first_seen)` (content-addressed cache), `slice_run`, `edge(a,b,signal,evidence)`, `cluster_override`, `template_blob`, `deny(repo_id|owner, reason)`, `adopter(repo_id, marketplace_ref, file)`, `scan_diff(scan_id, repo_id, change)`.
4. **`repo_daily` at 50k rows/day** is ~18M rows/year. Store daily snapshots only for Tier A/B (a few thousand) and **weekly** for Tier C, or store deltas only when stars/forks change. Skills table for Tier C: skip.
5. **Drop-out logic needs more states.** "Missing from two consecutive full sweeps => verify" is sound, but "still present => index lag, keep active" conflates distinct causes. Add states:
   - `unindexed`: verified present with marker, but not returned by code search. Expected causes per docs: archived, inactive > 1 year, huge repo [V-docs]. Keep active, tag why, and keep refreshing via direct verification.
   - `moved_private_or_deleted`: GraphQL returns null for a node id. GitHub does not distinguish private-ised from deleted; do not label `gone` as "deleted".
   - `demarked`: as planned.
   - Absence only counts if the covering `slice_run` rows were complete (section 2.4); a failed slice must not advance drop-out counters. Otherwise one rate-limit incident marks hundreds of repos missing.
   - Use a grace period measured in *complete sweeps of that marker*, not calendar days, because Tier C may be swept at different cadences.
6. **Verification cadence.** Re-verify only when something changed (marker blob sha differs, `pushedAt` differs from stored, or age > 30 days); everything else re-uses cached blobs. This is where the `blob` cache pays off.
7. **Stable identifiers for the site**: permalink by `databaseId`, not `full_name`, so shared links survive renames; redirect map for merged clusters.

---

## 6. UI/UX (section 7)

### 6.1 Static vs server
The static recommendation is right for Tier A+B and acceptable for Tier C, with these caveats:
- `repos.json.gz` on GitHub Pages: Pages will serve `.gz` as an opaque file unless you decompress client-side (`DecompressionStream`), and Pages already compresses `.json` responses on the wire [R]. Simplest: publish plain `.json` and let transport compression work, or keep `.gz` and decompress explicitly. Pick one and test.
- Prefer a **columnar JSON** layout (`{id:[...], stars:[...], ...}`) or Parquet for the 50k rows: roughly half the gzip size of an array of objects and faster to parse [R].
- Build the MiniSearch index at deploy time and ship it serialised (or build in a Web Worker); building a 50k-document full-text index on the main thread will freeze the page for seconds [R]. Index only name, description, topics and plugin names for the base table; load skill names lazily for Tier A/B.
- 50k rows in a virtualised table is fine, but **filtering and sorting must run on typed arrays or a worker**; re-rendering charts on every keystroke over 50k rows needs debounce and cross-filter on precomputed bins.
- Honest trigger for a server: Tier C > ~150k rows is fine as stated, but also if you want "report false positive" or alerts. Neither is in scope now, so static it is.

### 6.2 Filters and semantics
- Present orthogonal facets (`kind`, `native_level`, `evidence`) instead of A/B/C/D letters (section 1.4). Default view = native + verified-root, with a visible chip "Claude-compatible hidden (N)".
- Add: `dual_format`, `executes code` (hooks/MCP command/extensions/scripts), `pinned sources only`, `has external plugins`, `last pushed within 30/90/365 days` quick chips, `new this week`, `diverged fork` toggle, `valid / warnings`, `owner` multi-select, `topic` multi-select, `license` multi-select (not just boolean), `plugin name` and `skill name` search fields separate from repo-name search.
- Keep "show duplicates" but also show the cluster badge `+N copies` on the canonical row.

### 6.3 Sorts and default
- Default sort: stars desc is okay but low-star but active repos vanish; offer a "trending" sort (star delta 7d) once `repo_daily` has data, and "recently pushed". Persist sort and filters in the URL hash (the plan already has permalinks) and make the hash format stable and versioned.

### 6.4 Charts
Seven charts is more than the first release needs. Ship four: growth (first seen per week by native level), stars log histogram, top owners, component/executable mix. Add a "data freshness and coverage" mini-panel (recall estimate, canary pass/fail, slices incomplete) since honesty about coverage is the tool's differentiator. Charts must act as filters (click a bar => filter) and share the same filtered row set.

### 6.5 Detail panel
- Install snippets: show `copilot plugin marketplace add owner/repo` only when `evidence = verified-root` and `kind` includes marketplace; for nested manifests show `copilot plugin install owner/repo:path`; for a plugin inside a marketplace show `plugin@marketplace`. Add `#ref` form when a non-default branch is known [V-docs].
- Show *why* it was included: the matched marker paths with blob links (planned) and the evidence rows that made duplicates cluster (4.1).
- "Executes code" section listing hook events / MCP commands (names only, never rendering untrusted content as HTML).
- Add "what changed since last scan" and a "report this entry" link that opens a prefilled issue on your repo (feeds the deny-list).
- Copy-to-clipboard buttons on snippets, and `rel="noopener noreferrer nofollow"` on every outbound link.

### 6.6 Export and safety
- CSV export must **neutralise formula injection**: third-party descriptions can start with `=`, `+`, `-`, `@`; prefix with `'` or a tab for those cells. Add to section 9.
- Escape/`textContent` everywhere, add a CSP meta tag (no inline scripts, no remote images except `avatars.githubusercontent.com`), do not render README markdown.
- JSON export should include the filter state, scan id and generation time so exports are reproducible.

### 6.7 Accessibility and mobile
Plan mentions keyboard and colour; add a non-virtualised "table-like" ARIA grid pattern (virtualised tables often break screen-reader row counts), and a card layout under ~700 px. Persist column visibility.

---

## 7. Architecture, risks, open questions, phasing (sections 8 to 11)

### 7.1 Architecture/ops gaps
1. **One token, one bucket.** Nightly Actions, ad-hoc local runs, and the completeness checker all share one 10/min `search/code` limit and the user's 5,000-point GraphQL budget. Build the limiter around response headers (`x-ratelimit-remaining`, `x-ratelimit-reset`, `retry-after`), persist state between steps, and put the workflow in a `concurrency:` group with `cancel-in-progress: false`. Warn in docs that local runs steal the Action's budget [R for header names; standard].
2. **Open question 4 (`GITHUB_TOKEN` vs PAT):** I could not verify it. Test in Phase 0 with a throwaway workflow doing `gh api search/code` and printing `x-ratelimit-*` headers; also check whether the secondary-rate "10 per minute" applies per token or per installation. If a PAT is needed, a fine-grained PAT with no extra scopes is enough for public data [R]; keep it out of fork PR workflows (`pull_request_target` footgun).
3. **Actions constraints** [R]: 6 hour job limit; scheduled workflows in public repos are auto-disabled after 60 days of repo inactivity (data-only bot commits may not count), so add a heartbeat; cron jobs can be delayed or dropped at busy times, so make runs idempotent and resumable (the plan says resumable, good) and record `scan.status`.
4. **Resumability state** must itself be persisted (cursor per slice) outside the job workspace; keep it in the same SQLite or a small `state.json` artifact.
5. **Timeouts/retry policy**: define exponential backoff with jitter for 403 secondary limit, 429, 502/504 (GraphQL), and treat `incomplete_results` as a retry (section 2.1.5).
6. **Observability**: scan summary with per-stage counts, recall estimate, canary results, number of slices incomplete; fail the workflow if canaries fail or if row count drops > 10% vs previous scan.
7. **Reproducibility/testing**: unit-test the marker evaluator with recorded fixtures (positive and negative: `umbraco-marketplace.json`, nested `.github/plugin`, `.github/plugins` typo, root `plugin.json` from non-plugin ecosystems). Keep `markers.yaml` data-driven as planned, and add a "marker version" column so you can re-evaluate stored blobs after changing rules without refetching.
8. **Legal/ToS/privacy**: you are republishing third-party descriptions and links. Keep excerpts short, link to source, exclude emails, honour a takedown path (the "report this entry" link) and the deny-list. Respect GitHub's guidance on API use; no scraping of HTML [R].
9. **Security**: never clone or run anything (planned). Also do not follow arbitrary `source.url` values server-side with `httpx` (SSRF-ish and slow); only resolve GitHub-hosted references.

### 7.2 Risks to add to section 9
- Search backend instability (`incomplete_results`, regressing totals) [V-api].
- `sort` deprecation [V-docs].
- Non-searchable populations: archived, > 1 year inactive, huge repos [V-docs].
- Fuzzy `filename:` matching [V-api].
- Blob-oid collisions on boilerplate => over-merge.
- Git history bloat from committing data.
- Spec churn: Agent Plugins schema URLs (1.0.0, 1.1.0) and Copilot lookup order can change; keep a "docs fingerprint" job that fetches the CLI reference page, hashes it, and opens an issue on change.

### 7.3 Open questions: suggested answers
1. Tier C: scan fully nightly; at ~45 minutes to ~2 hours it is affordable (section 2.1.1).
2. Primary entity: repo table plus a first-class plugin view earlier than Phase 4, because de-dup is only sound at plugin level (section 4.2); the data model supports it from Phase 1 if you store plugin-dir tree oids.
3. Hosting: Pages with an Actions-built artifact; no committed data (section 5.1).
4. Token: unknown; test (section 7.1.2).
5. Adopters dataset: yes, as a secondary table, cheap and a good adoption/trending metric; but gate by star threshold in the UI.
6. npm/PyPI and Cursor/Codex attributes: keep Codex/Cursor as boolean co-occurrence flags (cheap), keep npm/PyPI as source kinds; they cost nothing extra.
7. Medium-signal aggressiveness: start conservative (union only on definitive edges), publish `similar_to` for the rest, and loosen only with audit precision numbers.

### 7.4 Phasing
- Add a **Phase 0b (half a day)**: token test, canary list, `-user:` negation test, `incomplete_results` behaviour, GraphQL response-size experiments with 10/25/50 repos x 8 blobs, and fixture capture for the marker evaluator.
- Move **plugin-level view and `executes code` badges** from Phase 4 to Phase 3: they are the product's differentiator and cost almost nothing once blobs are cached.
- Move the **completeness/recall number and canaries** from Phase 5 to Phase 1; without them you cannot tell whether a regression is data or code.
- Phase 3 estimate (2 to 3 days) looks light given virtualised table, search index, charts, URL state and accessibility; budget 4 to 5 days or cut charts to four.

---

## 8. Prioritised top-10 changes

1. **[must]** Fix section 2.1 and the verifier: Agent Plugins 1.0/1.1 manifests require both `$schema` and `name`; do not treat "closed field set" as a distinguisher; add `marketplace add owner/repo#ref` and non-default-branch marketplaces as known false negatives. [V-docs]
2. **[must]** Add an exact-basename, exact-path client-side filter for every code-search hit before it becomes a `marker_hit`, because `filename:marketplace.json` also matches `umbraco-marketplace.json`, `q-marketplace.json`, `Marketplace.json`; and replace the `-path:` chain for root markers with `path:/` queries (root marketplace ~400 to 1,600 raw hits, root AP manifest 2,440). [V-api, V-docs]
3. **[must]** Do not rely on `sort=indexed` for incremental scans (documented as "closing down"). Correct the arithmetic: a 450-request Tier C sweep is ~45 minutes, a realistic 1,000-request sweep ~1.7 h, so run full nightly sweeps and use blob `sha` change detection instead. [V-docs; arithmetic]
4. **[must]** Redesign storage: stop committing SQLite and 50k shards to git; keep the DB in a release asset/cache, deploy Pages from an artifact, pack details into ~500-repo shards, and add a content-addressed `blob` cache keyed by git blob oid. [R for git bloat; design]
5. **[must]** Harden de-dup: add `template_blob` exclusion (boilerplate blob oids shared by unrelated repos), restrict plain union-find to fork edges and equal `root_tree_sha`, treat other signals as `similar_to` edges with stored evidence, and add a divergence test so maintained hard-fork successors are not collapsed under their parent. [design; fork API fields V-api]
6. **[must]** Make absence handling robust: persist `slice_run` completeness and only advance drop-out counters when covering slices were complete; handle `incomplete_results: true` as retry (observed live); add `unindexed` and `moved_private_or_deleted` states because archived and inactive repos are non-searchable by design. [V-api, V-docs]
7. **[should]** Two-phase GraphQL verification: phase 1 `oid`/`byteSize` only, phase 2 `text` only for uncached blobs, batches of 20 to 25 repos, serialised; re-verify via `nodes(ids:)` using `node_id`. [R]
8. **[should]** Plugin-dir tree oid and SKILL.md blob oid as primary plugin/skill de-dup keys, plus an "executes code" attribute set (hooks, MCP commands, extensions, scripts) and `pinned sources` flag; surface in the UI and promote the plugin view to Phase 3. [design]
9. **[should]** Replace tiers A to D with orthogonal facets (`kind`, `native_level`, `evidence`, `dual_format`); add the extra discovery vectors (`.claude/settings.json`, `.vscode/settings.json` `chat.plugins.marketplaces`, README install snippets) and a recall estimate (capture-recapture) plus canary list in Phase 1. [V-docs for settings locations]
10. **[nice]** UI safety and polish: CSV formula-injection neutralisation, CSP and text-only excerpts, drop manifest emails, serialised pre-built search index in a worker, columnar JSON, charts as cross-filters (cap at four for v1), "report this entry" link feeding the deny-list. [design]
