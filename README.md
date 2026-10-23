# Copilot Plugin Finder

A census of public GitHub repositories that GitHub Copilot can register as a plugin
marketplace or install as a plugin, with metadata, de-duplication and (later) a static
browsing site. Design and research: [PLAN.md](PLAN.md); reviews and decisions in
[reviews/](reviews/); Phase 0b spike results in [docs/SPIKE-0b.md](docs/SPIKE-0b.md).

## Status

Phases 1 and 2 are implemented: partitioned, resumable code-search discovery; two-stage
GraphQL verification with a content-addressed blob cache; manifest parsing and facets;
graph expansion from marketplace `source` references, adopter settings files and fork
parents (with nested `owner/repo:path` plugins); de-duplication into clusters with
canonical repos, diverged-fork detection and a boilerplate guard; golden recall check;
offline re-classification; JSON export. Results: [docs/PHASE1-RESULTS.md](docs/PHASE1-RESULTS.md),
[docs/PHASE2-RESULTS.md](docs/PHASE2-RESULTS.md), audit sample [docs/dedup-audit.md](docs/dedup-audit.md).
Phase 3 (static site) is implemented in `site/`: Vite + TypeScript, TanStack table-core and
virtual-core, Chart.js and MiniSearch; see [docs/PHASE3-RESULTS.md](docs/PHASE3-RESULTS.md).

## Site

```bash
uv run cpf site          # writes site/public/data (repos.json, plugins.json, meta.json, detail shards)
cd site
npm ci                   # Node 24 via nvm-windows: `nvm install lts && nvm use lts`
npm run dev              # http://localhost:5173
npm run build            # type-check + production build to site/dist (CSP injected at build time)
```

The workflow in `.github/workflows/scan.yml` runs the scan, exports the data, builds the
site and deploys `site/dist` to GitHub Pages.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and a GitHub token (`GITHUB_TOKEN`, or a
logged-in `gh` CLI, which is used automatically).

```bash
uv sync --group dev
uv run pytest -q
```

On Windows set `PYTHONUTF8=1` in the environment before running.

## Commands

```bash
uv run cpf scan --group copilot-authored,pointers    # discover + verify + golden + export
uv run cpf discover --group copilot-authored          # code-search sweeps only
uv run cpf discover --family M-GH --no-forks          # one family
uv run cpf verify                                     # GraphQL verification of pending repos
uv run cpf verify --names owner/repo,owner2/repo2     # verify specific repos directly
uv run cpf expand                                     # follow marketplace/adopter/parent references to unseen repos
uv run cpf dedup                                      # edges, clusters, canonical repos; writes docs/dedup-audit.md
uv run cpf reclassify                                 # recompute facets from cached blobs after a rule change (offline)
uv run cpf golden                                     # golden recall set (exit 3 on a miss)
uv run cpf export                                     # data/export/{repos,plugins,meta}.json
uv run cpf stats                                      # database statistics
```

Marker families and partition axes live in `rules/markers.yaml`; the golden set in
`rules/golden.yaml`. The database is `data/index.sqlite` (ignored by git).

## Layout

```
rules/        markers.yaml, golden.yaml
scanner/cpf/  config, db (schema), gh (client), markers, discover, manifest, verify, golden, export, cli
scanner/tests/
data/         index.sqlite, export/ (generated)
docs/         SPIKE-0b.md
.github/workflows/scan.yml   nightly run (database kept in the Actions cache, exports as artifacts)
```

## How a repo gets in

1. A code-search hit whose path matches a family's exact path regex becomes a `marker_hit`
   and a `candidate` repo.
2. V1 (GraphQL, ~50 repos/query) fetches repository facts and the root tree; unchanged
   head commits stop here.
3. V2 lists the manifest directories that exist and fetches only blobs not already cached.
4. Manifests are parsed in Copilot CLI lookup order; the first existing path is the
   *effective* manifest, later valid ones are *shadowed*. Facets (`kind`, `native_level`,
   `evidence`, `format`, `dual_format`, `copilot_specific`, `executes_code`) and the plugin
   list (from marketplace entries first) are stored, and the repo becomes `active`,
   `invalid` (manifest present but unusable) or `demarked`.
