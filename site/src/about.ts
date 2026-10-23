// "About the data" view: coverage, scan status, marker census and caveats.
import type { Meta } from "./data";
import { el, link } from "./dom";

export function renderAbout(meta: Meta | null, generated: string): HTMLElement {
  const root = el("div", { class: "about" });
  root.append(el("h2", {}, "About the data"));
  if (!meta) { root.append(el("p", {}, "Metadata not available.")); return root; }
  const p = (t: string) => el("p", {}, t);
  root.append(p(`Data generated ${generated || meta.generated_at}. ${meta.repos_active.toLocaleString()} active repositories, ${meta.repos_canonical.toLocaleString()} after de-duplication (${meta.clusters.toLocaleString()} clusters, ${meta.diverged_forks} diverged forks kept separate), ${meta.plugins.toLocaleString()} plugins at their home repositories, ${meta.adopters.toLocaleString()} repositories that name a marketplace in their settings.`));
  const ls = meta.last_full_scan;
  if (ls) root.append(p(`Last full scan #${ls.id}: started ${ls.started}, finished ${ls.finished ?? "—"}, status ${ls.status}; ${ls.repos_verified?.toLocaleString() ?? "?"} repositories verified.`));
  if (meta.golden_recall !== null) root.append(p(`Golden recall set: ${(meta.golden_recall * 100).toFixed(0)}% of the known-good repositories were found and verified at root.`));
  if (meta.slices_incomplete) root.append(el("p", { class: "callout" }, `${meta.slices_incomplete} search slice(s) reported incomplete results in the last 3 days; coverage of those families may be partial until the next run.`));

  root.append(el("h3", {}, "How repositories get in"));
  root.append(p("A repository is included when GitHub code search finds a Copilot plugin or marketplace manifest at a path the Copilot CLI reads, or when a marketplace, a settings file or a fork relation names it. Every candidate is then verified against the repository's default branch over the GitHub GraphQL API: the manifest must exist at the exact path and parse with the required fields. The effective manifest is the first one in Copilot's lookup order; valid manifests behind an invalid first one are reported as shadowed."));
  root.append(p("Levels: \"Copilot-authored\" means a manifest under .github/plugin/, .plugin/, a root Agent Plugins manifest, or Copilot-specific components (com.github.copilot/, SDK extensions). \"Copilot-installable (Claude format)\" means only .claude-plugin/ manifests were found; Copilot CLI reads those too, but only skills and MCP servers are guaranteed to apply. The default view shows Copilot-authored, canonical repositories; toggles reveal the rest."));
  root.append(el("h3", {}, "Marker census (repositories per search family)"));
  const t = el("table", {}, el("thead", {}, el("tr", {}, el("th", {}, "Family"), el("th", {}, "Repositories"))));
  const tb = el("tbody");
  for (const m of meta.markers) tb.append(el("tr", {}, el("td", {}, m.marker_id), el("td", {}, m.repos.toLocaleString())));
  t.append(tb);
  root.append(t);
  root.append(el("h3", {}, "Known limits"));
  const ul = el("ul", { class: "list" });
  for (const s of [
    "GitHub code search returns at most 1,000 results per query and 10 queries per minute; sweeps are partitioned by file size, content terms and owner, and counts it reports are estimates.",
    "Archived repositories, repositories inactive for about a year, very large repositories and most zero-star forks are not indexed by code search; they can only arrive through references. Fork counts come from GitHub's forkCount, not from search.",
    "De-duplication merges forks (unless they diverged), identical trees, and pairs with two independent strong signals (same manifest blob, same README blob, shared plugin directory). Single-signal matches are listed as evidence only. Boilerplate blobs shared by many unrelated owners are ignored.",
    "Star counts and dates are as of the last verification of each repository; copies inherit nothing from their canonical repository.",
    "Third-party text (descriptions, README excerpts, manifest fields) is shown as plain text and truncated; nothing from a repository is executed. Report a wrong entry with the link in its detail panel.",
  ]) ul.append(el("li", {}, s));
  root.append(ul);
  root.append(el("h3", {}, "Sources"));
  root.append(el("p", {}, link("https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference", "GitHub Copilot CLI plugin reference"), " · ", link("https://agent-plugins.org/specification", "Agent Plugins specification"), " · ", link("https://code.visualstudio.com/docs/agent-customization/agent-plugins", "Agent plugins in VS Code")));
  return root;
}
