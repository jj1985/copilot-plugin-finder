# Phase 3 results: static site (2026-10-22)

## Stack

Vite 6.4 + TypeScript 5.9, `@tanstack/table-core` (sorting) and `@tanstack/virtual-core`
(row virtualisation), Chart.js 4 (tree-shaken bar charts), MiniSearch (prefix/fuzzy search),
no framework. Node 24 LTS installed with nvm-windows. Production bundle: 296 KB JS
(96 KB gzipped), 7.5 KB CSS. Data is read from `site/public/data`, written by `cpf site`.

## Data files

| File | Size | Content |
|---|---|---|
| `repos.json` | 3.4 MB | 8,348 active repos, columnar, dictionary-encoded owner/language/license |
| `plugins.json` | 4.5 MB | 17,249 plugins at their home (canonical) repos, with distributor counts |
| `detail/NNN.json` | 42 shards, ~0.6 MB each (25 MB total) | per-repo manifests, plugins, markers, cluster members, evidence edges, adopters, README excerpt; loaded on click |
| `meta.json` | 1.5 KB | scan status, counts, golden recall, marker census |

## Features implemented (PLAN.md §7)

- Repositories tab: virtualised, sortable grid (shift-click for multi-sort); columns for
  name and description, level, kind, format, stars, network size, indexed copies, plugin
  count, reverse references, runs-code badges, language, license, created, last commit, flags.
- Facets with live counts: level, kind, format, runs-code, evidence, owner type, language,
  license; stars range; plugin and reference minimums; created date range; last-commit-within
  chips; archived / template / fork tri-states; validation; listed-by-seed, dual format,
  Copilot-specific, show copies, diverged-forks-only; topic chip. Default view is Copilot-authored
  canonical repos.
- Search over name, description, marketplace name and topics (MiniSearch, prefix + light fuzzy).
- Four cross-filter charts: creation month stacked by level, stars distribution, top owners,
  components that run code. Clicking a bar applies the matching filter.
- Detail panel: badges, repository facts, install snippets with copy buttons (marketplace add,
  plugin install by name, `owner/repo:path` for nested plugins; warning for marketplaces named
  `awesome-copilot`), "why it is included" with links to the exact manifest blobs at the verified
  commit, effective and shadowed manifests, validation warnings, plugin list (external sources
  linked to their repo entry), marketplaces that list it, settings files that name it, cluster
  members and evidence edges, README excerpt, code-search and report links.
- Plugins tab: grid of plugins at their home repo with repo link, path, level, format, version,
  repo stars, number of other marketplaces listing it, runs-code badges, category; facets and
  search; row click opens the home repo's detail.
- About tab: coverage, last scan, golden recall, incomplete-slice warning, inclusion rules,
  marker census table, known limits, sources.
- CSV / JSON export of the current sorted view (formula-injection neutralised, context included).
- URL hash state (versioned) for tab, filters and sort; Escape closes the panel.
- Safety: no innerHTML anywhere, all third-party text via textContent with length caps and bidi
  stripping, https-only links with `rel="noopener noreferrer nofollow"`, CSP meta injected at
  build time (`default-src 'self'`, no inline script or style).
- Responsive: under 640 px the grid becomes a card list and charts hide; a "Plain table" mode
  renders up to 500 rows without virtualisation for screen readers.

## Verified in the browser pane

Repositories view (4,185 of 8,348 in the default view), detail panel for `DietrichGebert/ponytail`
(install snippets, 289 adopters, two distributors), Plugins tab (17,249 plugins), About tab,
mobile card layout. No console errors after the TanStack state fix.

## Defects found and fixed

1. TanStack table-core does not merge a partial `state` with its initial state; header groups
   crashed until the full initial state was supplied.
2. The CSP meta tag blocked Vite's dev-server style injection; it is now injected by a
   build-only Vite plugin, and `frame-ancestors` (ignored in meta tags) was dropped.
3. The first site export carried plugin rows for every fork and 40 MB of detail shards; plugins
   are now exported for canonical repos only and copies omit their plugin lists.

## Not done

- No deploy has happened; the Pages job in `scan.yml` is untested.
- MiniSearch runs on the main thread (index build ~0.3 s for 8k repos, ~0.6 s for 17k plugins);
  a worker was not needed at this size.
- No Skills tab, trending or adoption sorts (need snapshots over time), facet counts for topics,
  or column visibility persistence.
- The "report this entry" link points at a repository that does not exist yet
  (`REPORT_URL` in `site_export.py`).
