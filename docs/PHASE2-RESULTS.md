# Phase 2 results: graph expansion and de-duplication (2026-10-22)

## Expansion

Referral sources materialised into the `referral` table: marketplace `source` objects
(`plugin_ref`), adopter settings files (`adopter`), and parents of active forks.

| Measure | Value |
|---|---|
| Referral rows | 19,857 |
| Rounds until the frontier was empty | 3 |
| Repos looked up by name | 2,443 |
| Found and verified | 2,029 |
| Not found (deleted, private, renamed) | 414 (recorded in `deny` with reason `expand: not found`) |
| GraphQL points | 715 |
| Nested plugins verified via `owner/repo:path` | 29 (`evidence = verified-nested`) |
| Active repos before → after | 6,694 → 8,348 |
| Copilot-authored / Claude-format-only (active) | 6,048 / 2,300 |
| Declared-only (named, but no manifest) | 153 |
| Adopter repos | 4,205 (5,011 settings references) |

Reverse references are now populated: `referenced_by_marketplaces` (distinct non-fork
marketplaces listing the repo), `referenced_by_settings` (distinct repos whose settings
name it), `listed_by_seed`. Most-adopted marketplaces by settings references:
`anthropics/claude-plugins-official` 376, `DietrichGebert/ponytail` 289,
`JuliusBrussee/caveman` 193, `nrwl/nx-ai-agents-config` 174, `openai/codex-plugin-cc` 154.
Most-listed plugin repos across non-fork marketplaces: `microsoft/Dataverse-skills` 11,
`dotnet/modernize-dotnet`, `MicrosoftDocs/mcp`, `figma/mcp-server-guide`, `dotnet/skills` 9 each.

## De-duplication

| Measure | Value |
|---|---|
| Active repos clustered | 8,348 |
| Clusters (canonical repos) | 6,467 |
| &nbsp;&nbsp;Copilot-authored canonical | 4,185 (4,080 non-fork) |
| &nbsp;&nbsp;Claude-format canonical | 2,282 |
| Multi-member clusters | 355 |
| Largest cluster | `github/awesome-copilot`: 362 members (forks + 7 detached clones) |
| Diverged forks kept as their own record | 69 (e.g. `lucianghinda/superpowers-ruby`, `triuzzi/brave-devtools-mcp`, `legalese/l4-ide`) |
| Boilerplate blobs excluded from evidence | 26 |
| Edges: fork / tree / manifest / readme / plugin_tree / strong2 / strong2_blocked / template | 1,864 / 447 / 621 / 529 / 1,372 / 330 / 67 / 5 |
| Plugin entries on canonical repos (of 60,556 total) | 19,863; 7,273 distinct plugin directory trees |

Rules as implemented (`scanner/cpf/dedup.py`): union-find on fork edges that pass the
divergence test and on identical non-trivial root trees; two independent strong signals
(same effective manifest blob, same README blob, shared plugin directory tree) also merge,
unless the pair or either side's cluster root is a diverged fork; a single strong signal is
kept as a `similar_to` edge only; template relations are recorded, never merged. Canonical
choice: active and verified at root, then non-fork, then listed by a seed marketplace, then
oldest, then most stars, then organisation.

## Audit sample

`docs/dedup-audit.md` lists the size distribution, the 25 largest clusters, 25 random
non-fork clone pairs, the diverged forks and 25 single-signal "similar" pairs. A read
through the sample found the clone pairs to be genuine copies (career-ops, headroom and
awesome-copilot re-uploads under new names) and the diverged forks to be real spin-offs.
Open tuning question: a maintainer's working fork with the same marketplace name and a few
dozen stars (e.g. `burkeholland/awesome-copilot`, 36★) is currently treated as diverged;
raising `DIVERGED_MIN_STARS` when the marketplace name is unchanged would fold those back.
Per-signal precision has not been labelled by hand yet (PLAN.md §5.4).

## Defects found and fixed during Phase 2

1. `lspServers` is not a Copilot-authorship signal (Claude Code plugins have LSP config);
   it had labelled `anthropics/claude-plugins-official` as Copilot-authored. 38 repos re-verified.
2. Diverged forks were merged back into the parent cluster through shared README and plugin
   trees (4 cases); strong-signal unions now stop at diverged fork edges (`strong2_blocked`).
3. The de-dup summary over-counted repeated pair signals; counts now come from the `edge` table.

## New capabilities

- `cpf expand`, `cpf dedup`, `cpf reclassify` (offline facet recomputation from stored root and
  directory listings, so a rule change does not need a network pass), and `cpf scan` runs the
  full chain: discover → verify → expand → golden → dedup → export.
- `repo_state` now stores root entries, directory listings and manifest paths per repo.

## Not done / caveats

- Phase 3 (static site) not started; exports are still row-oriented JSON (16 MB + 30 MB).
- First-commit and SKILL.md-set signals are not implemented (plugin directory trees cover
  most of their value).
- `cluster_override` supports `merge` only; `split` is recorded but not applied.
- 414 unresolved names sit in `deny` and are never retried; a monthly retry is a Phase 5 item.
