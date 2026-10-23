// Slide-over detail panel for a repository.
import { EVIDENCE_LABEL, KIND_LABEL, LEVEL_LABEL, loadDetail, type Detail, type Meta, type Repo } from "./data";
import { badge, clean, copyButton, el, fmtNum, ghBlob, ghRepo, link } from "./dom";

const aside = () => document.getElementById("detail") as HTMLElement;
const backdrop = () => document.getElementById("backdrop") as HTMLElement;

export function closeDetail(): void {
  aside().classList.remove("open");
  aside().setAttribute("aria-hidden", "true");
  backdrop().hidden = true;
}

export async function openDetail(repo: Repo, meta: Meta | null, findRepo: (name: string) => Repo | undefined, onOpen: (r: Repo) => void): Promise<void> {
  const a = aside();
  a.replaceChildren(el("button", { class: "btn close", type: "button", "aria-label": "Close" }, "✕"), el("h2", {}, repo.name), el("p", { class: "muted" }, "Loading…"));
  a.classList.add("open");
  a.setAttribute("aria-hidden", "false");
  backdrop().hidden = false;
  a.querySelector(".close")!.addEventListener("click", closeDetail);
  backdrop().onclick = closeDetail;
  let d: Detail | null = null;
  try {
    d = await loadDetail(repo);
  } catch (e) {
    a.append(el("p", { class: "callout" }, `Could not load details: ${(e as Error).message}`));
    return;
  }
  if (!d) { a.append(el("p", { class: "callout" }, "No detail record for this repository.")); return; }
  a.replaceChildren(...render(repo, d, meta, findRepo, onOpen));
  a.querySelector(".close")!.addEventListener("click", closeDetail);
  a.scrollTop = 0;
  (a.querySelector(".close") as HTMLElement).focus();
}

function section(title: string, ...children: (Node | string | null | false | undefined)[]): Node[] {
  return [el("h3", {}, title), ...children.filter(Boolean) as Node[]];
}

function snippet(cmd: string): HTMLElement {
  return el("div", { class: "snippet" }, el("code", {}, cmd), copyButton(cmd));
}

function render(repo: Repo, d: Detail, meta: Meta | null, findRepo: (name: string) => Repo | undefined, onOpen: (r: Repo) => void): Node[] {
  const out: Node[] = [];
  out.push(el("button", { class: "btn close", type: "button", "aria-label": "Close" }, "✕"));
  out.push(el("h2", {}, link(ghRepo(repo.name), repo.name)));
  const badges = el("div", {},
    badge(LEVEL_LABEL[repo.level], repo.level === 0 ? "copilot" : "claude"),
    badge(KIND_LABEL[repo.kind] ?? repo.kind),
    repo.format ? badge(repo.format) : null,
    badge(EVIDENCE_LABEL[repo.evidence], repo.evidence === 0 ? "ok" : "warn"),
    repo.dual ? badge("dual format", "ok") : null,
    repo.copspec ? badge("Copilot-specific components") : null,
    repo.archived ? badge("archived", "warn") : null,
    repo.is_fork ? badge(d.diverged ? "diverged fork" : "fork", d.diverged ? "warn" : "") : null,
    repo.canonical ? null : badge("copy of a canonical repo", "warn"),
    ...(repo.exec ? repo.exec.split(",").map((x) => badge(`runs: ${x}`, "exec")) : []),
  );
  out.push(badges);
  if (d.desc) out.push(el("p", {}, clean(d.desc, 600)));

  // facts
  const dl = el("dl", { class: "kv" });
  const kv = (k: string, v: Node | string | null | undefined) => { if (v === null || v === undefined || v === "") return; dl.append(el("dt", {}, k), el("dd", {}, v)); };
  kv("Stars / forks", `${fmtNum(repo.stars)} / ${fmtNum(repo.forks)}`);
  kv("Network / indexed copies", repo.canonical ? `${fmtNum(repo.network)} / ${fmtNum(repo.copies)}` : null);
  kv("Owner", `${repo.owner} (${repo.owner_type === "O" ? "organisation" : "user"})`);
  kv("Created / last commit", `${repo.created} / ${repo.committed}`);
  kv("Language / license", `${d.language ?? "—"} / ${d.license ?? "none"}`);
  kv("Latest release", d.latest_release);
  kv("Fork of", d.parent ? link(ghRepo(d.parent), d.parent) : null);
  kv("Generated from template", d.template ? link(ghRepo(d.template), d.template) : null);
  kv("Homepage", d.homepage ? link(d.homepage, d.homepage) : null);
  kv("Topics", d.topics.length ? d.topics.join(", ") : null);
  kv("Listed by seed marketplace", d.seed);
  kv("Named in settings files", d.adopter_count ? String(d.adopter_count) : null);
  kv("Listed by marketplaces", repo.ref_mk ? String(repo.ref_mk) : null);
  kv("First seen / last verified", `${d.first_seen.slice(0, 10)} / ${(d.last_verified ?? "").slice(0, 10)}`);
  out.push(...section("Repository", dl));

  // install
  const installs: HTMLElement[] = [];
  const isMarketplace = repo.kind === "m" || repo.kind === "b";
  const isPlugin = repo.kind === "p" || repo.kind === "b";
  if (isMarketplace && repo.evidence === 0) {
    installs.push(snippet(`copilot plugin marketplace add ${repo.name}`));
    const mkName = d.marketplace?.name;
    for (const p of d.plugins.slice(0, 3)) if (mkName) installs.push(snippet(`copilot plugin install ${p.name}@${mkName}`));
    if (mkName === "awesome-copilot" && repo.name.toLowerCase() !== "github/awesome-copilot") {
      installs.push(el("div", { class: "callout" }, "This marketplace is named \"awesome-copilot\", which collides with the built-in default marketplace; Copilot registers marketplaces by manifest name, so adding it may be refused or shadow the built-in one."));
    }
  }
  if (isPlugin) {
    const dir = d.pl_path ? d.pl_path.replace(/(^|\/)(\.github\/plugin\/|\.plugin\/|\.claude-plugin\/)?plugin\.json$/, "") : "";
    installs.push(snippet(dir ? `copilot plugin install ${repo.name}:${dir.replace(/\/$/, "")}` : `copilot plugin install ${repo.name}`));
  }
  if (repo.level === 1) installs.push(el("p", { class: "muted" }, "Claude-format manifests are read by Copilot CLI from .claude-plugin/; components beyond skills and MCP servers may not apply."));
  if (installs.length) out.push(...section("Install", ...installs));

  // manifests / why included
  const why = el("ul", { class: "list" });
  for (const m of d.markers) why.append(el("li", {}, `${m.marker}: `, link(ghBlob(repo.name, d.head, m.path), m.path)));
  if (!d.markers.length) why.append(el("li", { class: "muted" }, "Not found by search; reached through a marketplace, settings file or fork-parent reference."));
  const eff = el("dl", { class: "kv" });
  if (d.mk_path) eff.append(el("dt", {}, "Effective marketplace manifest"), el("dd", {}, link(ghBlob(repo.name, d.head, d.mk_path), d.mk_path)));
  if (d.pl_path) eff.append(el("dt", {}, "Effective plugin manifest"), el("dd", {}, link(ghBlob(repo.name, d.head, d.pl_path), d.pl_path)));
  if (d.shadowed.length) eff.append(el("dt", {}, "Shadowed manifests"), el("dd", {}, d.shadowed.join(", ")));
  if (d.marketplace) eff.append(el("dt", {}, "Marketplace"), el("dd", {}, `${d.marketplace.name}${d.marketplace.version ? " v" + d.marketplace.version : ""}${d.marketplace.owner ? " by " + clean(d.marketplace.owner, 80) : ""}`));
  if (d.plugin) eff.append(el("dt", {}, "Plugin"), el("dd", {}, `${d.plugin.name}${d.plugin.version ? " v" + d.plugin.version : ""}`));
  out.push(...section("Why it is included", why, eff));
  if (d.warnings.length) out.push(el("div", { class: "callout" }, el("strong", {}, "Validation: "), d.warnings.map((w) => clean(w, 200)).join(" · ")));

  // plugins
  if (d.plugins.length || d.plugins_total) {
    const ul = el("ul", { class: "list" });
    for (const p of d.plugins.slice(0, 60)) {
      const li = el("li", {}, el("strong", {}, clean(p.name, 80)), p.version ? ` v${clean(p.version, 20)}` : "", " ");
      if (p.source_kind === "github" && p.source_repo) {
        const target = findRepo(p.source_repo);
        li.append("← ", target ? el("a", { href: "#", class: "inlink" }, p.source_repo) : link(ghRepo(p.source_repo), p.source_repo), p.path ? `:${p.path}` : "", p.pinned ? " (pinned)" : "");
        if (target) li.querySelector("a.inlink")!.addEventListener("click", (e) => { e.preventDefault(); onOpen(target); });
      } else if (p.source_kind && p.source_kind !== "local" && p.source_kind !== "self") {
        li.append(badge(`external: ${p.source_kind}`));
      }
      for (const x of p.exec) li.append(" ", badge(x, "exec"));
      if (p.desc) li.append(el("div", { class: "muted" }, clean(p.desc, 160)));
      ul.append(li);
    }
    const note = d.plugins.length < d.plugins_total ? el("p", { class: "muted" }, repo.canonical ? `Showing ${d.plugins.length} of ${d.plugins_total}.` : `This is a copy; plugin list (${d.plugins_total}) is shown on the canonical repository.`) : null;
    out.push(...section(`Plugins (${d.plugins_total})`, ul, note));
  }

  // listed in / adopters
  if (d.listed_in.length) {
    const ul = el("ul", { class: "list" });
    for (const l of d.listed_in) ul.append(el("li", {}, repoLink(l.marketplace, findRepo, onOpen), ` as "${clean(l.entry, 60)}"`));
    out.push(...section("Listed by marketplaces", ul));
  }
  if (d.adopters.length) {
    const ul = el("ul", { class: "list" });
    for (const x of d.adopters.slice(0, 25)) ul.append(el("li", {}, link(ghRepo(x.repo), x.repo), ` (${fmtNum(x.stars)}★)`));
    out.push(...section(`Named in settings files (${d.adopter_count})`, ul, d.adopter_count > 25 ? el("p", { class: "muted" }, "Showing the 25 most starred.") : null));
  }

  // cluster
  if (d.cluster.members.length || d.cluster.edges.length) {
    const ul = el("ul", { class: "list" });
    for (const m of d.cluster.members) ul.append(el("li", {}, repoLink(m.name, findRepo, onOpen), ` (${m.fork ? "fork" : "clone"}, ${fmtNum(m.stars)}★)`, m.canonical ? " — canonical" : ""));
    const ev = el("ul", { class: "list" });
    for (const e of d.cluster.edges.slice(0, 20)) ev.append(el("li", {}, `${e.signal}: `, repoLink(e.other, findRepo, onOpen)));
    out.push(...section(`Duplicates and evidence (cluster ${d.cluster.id ?? "—"})`,
      d.cluster.members.length ? ul : el("p", { class: "muted" }, "No other indexed member."),
      d.cluster.edges.length ? el("details", {}, el("summary", {}, `${d.cluster.edges.length} evidence edge(s)`), ev) : null));
  }

  if (d.readme) out.push(...section(`README (${d.readme_name ?? ""})`, el("p", { class: "muted" }, clean(d.readme, 400))));

  // footer links
  const q = encodeURIComponent(`repo:${repo.name} filename:marketplace.json OR filename:plugin.json`);
  const report = meta?.report_url ? `${meta.report_url}?title=${encodeURIComponent("Entry: " + repo.name)}&body=${encodeURIComponent("Repository: https://github.com/" + repo.name + "\nIssue: ")}` : null;
  out.push(...section("Links",
    el("p", {}, link(`https://github.com/search?type=code&q=${q}`, "Open this repo's manifests in GitHub code search"), " · ",
      report ? link(report, "Report this entry") : "", " · ", link(ghRepo(repo.name), "Repository"))));
  return out;
}

function repoLink(name: string, findRepo: (n: string) => Repo | undefined, onOpen: (r: Repo) => void): HTMLElement {
  const target = findRepo(name);
  if (!target) return link(ghRepo(name), name);
  const a = el("a", { href: "#" }, name);
  a.addEventListener("click", (e) => { e.preventDefault(); onOpen(target); });
  return a;
}
