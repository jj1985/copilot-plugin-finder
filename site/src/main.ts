import "./style.css";
import MiniSearch from "minisearch";
import type { SortingState } from "@tanstack/table-core";
import { EVIDENCE_LABEL, KIND_LABEL, LEVEL_LABEL, loadMeta, loadPlugins, loadRepos, type Meta, type Plugin, type Repo } from "./data";
import { badge, clean, el, fmtNum, ghRepo, link } from "./dom";
import { defaultFilters, facetCounts, fromHash, passes, toHash, type FacetKey, type FilterState } from "./filters";
import { Grid } from "./grid";
import { Charts, type ChartAction } from "./charts";
import { closeDetail, openDetail } from "./detail";
import { renderAbout } from "./about";
import { exportRows } from "./exporter";

// ---------------- state ----------------
let repos: Repo[] = [];
let plugins: Plugin[] | null = null;
let meta: Meta | null = null;
let generated = "";
let tab = "repos";
let filters: FilterState = defaultFilters();
let sortKey = "";
const byName = new Map<string, Repo>();
let repoSearch: MiniSearch<Repo> | null = null;
let searchHits: Set<number> | null = null; // null = no query
let pluginFilters = { q: "", level: new Set<number>([0]), format: new Set<string>(), exec: new Set<string>(), seedOnly: false, distributed: false, kind: new Set<string>() };
let pluginSearch: MiniSearch<Plugin & { id: number }> | null = null;

const main = () => document.getElementById("main") as HTMLElement;
const findRepo = (name: string) => byName.get(name.toLowerCase());
const openRepo = (r: Repo) => { void openDetail(r, meta, findRepo, openRepo); };

// ---------------- repositories view ----------------
const repoGrid = new Grid<Repo>({
  ariaLabel: "Repositories",
  rowHeight: 42,
  initialSort: [{ id: "stars", desc: true }],
  onSortChange: (s) => { sortKey = s.map((x) => `${x.desc ? "-" : ""}${x.id}`).join(","); pushHash(); },
  rowClass: (r) => (r.canonical ? "" : "copy"),
  onRowClick: openRepo,
  columns: [
    { id: "name", header: "Repository", width: "minmax(260px,2fr)", accessor: (r) => r.name, cell: (r) => {
      const n = el("div", { class: "name" }, link(ghRepo(r.name), r.name));
      n.append(el("small", {}, clean(r.desc ?? "", 120)));
      return n;
    } },
    { id: "level", header: "Level", width: "150px", accessor: (r) => r.level, num: true, cell: (r) => badge(r.level === 0 ? "Copilot" : "Claude fmt", r.level === 0 ? "copilot" : "claude") },
    { id: "kind", header: "Kind", width: "90px", accessor: (r) => r.kind, cell: (r) => ({ m: "marketplace", p: "plugin", b: "both" }[r.kind] ?? r.kind) },
    { id: "format", header: "Format", width: "140px", accessor: (r) => r.format ?? "", cell: (r) => r.format ?? "" },
    { id: "stars", header: "Stars", width: "70px", accessor: (r) => r.stars, num: true, cell: (r) => fmtNum(r.stars) },
    { id: "network", header: "Network", width: "80px", accessor: (r) => r.network ?? -1, num: true, cell: (r) => (r.canonical ? fmtNum(r.network) : "") },
    { id: "copies", header: "Copies", width: "70px", accessor: (r) => r.copies ?? -1, num: true, cell: (r) => (r.canonical ? fmtNum(r.copies) : "") },
    { id: "plugins", header: "Plugins", width: "70px", accessor: (r) => r.plugins, num: true },
    { id: "refs", header: "Refs", width: "60px", accessor: (r) => r.ref_mk + r.ref_set, num: true, cell: (r) => String(r.ref_mk + r.ref_set || "") },
    { id: "exec", header: "Runs code", width: "170px", accessor: (r) => r.exec, cell: (r) => { const d = el("div"); for (const x of r.exec ? r.exec.split(",") : []) d.append(badge(x === "copilot-components" ? "copilot dir" : x, "exec")); return d; } },
    { id: "language", header: "Language", width: "100px", accessor: (r) => r.language ?? "", cell: (r) => r.language ?? "" },
    { id: "license", header: "License", width: "100px", accessor: (r) => r.license ?? "", cell: (r) => r.license ?? "" },
    { id: "created", header: "Created", width: "95px", accessor: (r) => r.created },
    { id: "committed", header: "Last commit", width: "95px", accessor: (r) => r.committed },
    { id: "flags", header: "Flags", width: "190px", accessor: (r) => (r.archived ? 1 : 0) + (r.nwarn ? 2 : 0), num: true, cell: (r) => {
      const d = el("div");
      if (r.archived) d.append(badge("archived", "warn"));
      if (r.template) d.append(badge("template"));
      if (r.is_fork) d.append(badge(r.diverged ? "diverged fork" : "fork", r.diverged ? "warn" : ""));
      if (r.dual) d.append(badge("dual", "ok"));
      if (r.seed) d.append(badge("seed-listed", "ok"));
      if (r.nwarn) d.append(badge(`${r.nwarn} warning${r.nwarn > 1 ? "s" : ""}`, "warn"));
      if (r.evidence === 1) d.append(badge("nested", "warn"));
      if (!r.canonical) d.append(badge("copy", "warn"));
      return d;
    } },
  ],
});
const charts = new Charts(onChartAction);
let sidebar: HTMLElement;
let toolbar: HTMLElement;
let countEl: HTMLElement;

function buildReposView(): HTMLElement {
  sidebar = el("aside", { class: "sidebar", "aria-label": "Filters" });
  countEl = el("span", { class: "count" });
  const plainBtn = el("button", { class: "btn small", type: "button", "aria-pressed": "false" }, "Plain table");
  plainBtn.addEventListener("click", () => { const on = plainBtn.getAttribute("aria-pressed") !== "true"; plainBtn.setAttribute("aria-pressed", String(on)); repoGrid.setPlain(on); });
  const chartsBtn = el("button", { class: "btn small", type: "button", "aria-pressed": "true" }, "Charts");
  chartsBtn.addEventListener("click", () => { const on = chartsBtn.getAttribute("aria-pressed") !== "true"; chartsBtn.setAttribute("aria-pressed", String(on)); charts.root.classList.toggle("collapsed", !on); });
  const csv = el("button", { class: "btn small", type: "button" }, "Export CSV");
  const json = el("button", { class: "btn small", type: "button" }, "Export JSON");
  csv.addEventListener("click", () => doExport("csv"));
  json.addEventListener("click", () => doExport("json"));
  const reset = el("button", { class: "btn small", type: "button" }, "Reset filters");
  reset.addEventListener("click", () => { filters = defaultFilters(); applyRepos(); });
  toolbar = el("div", { class: "toolbar" }, countEl, el("span", { class: "spacer" }), chartsBtn, plainBtn, csv, json, reset);
  const content = el("div", { class: "content" }, toolbar, charts.root, repoGrid.root);
  return el("div", { class: "view" }, sidebar, content);
}

const REPO_EXPORT_COLS = ["name", "owner", "owner_type", "desc", "stars", "forks", "created", "committed", "is_fork", "parent", "archived", "language", "license", "kind", "level", "evidence", "format", "dual", "exec", "mk_path", "pl_path", "mk_name", "plugins", "ext_plugins", "nwarn", "cluster", "canonical", "network", "copies", "diverged", "ref_mk", "ref_set", "seed", "topics"];
function doExport(kind: "csv" | "json"): void {
  const rows = repoGrid.sortedRows().map((r) => ({ ...r, url: ghRepo(r.name), level: LEVEL_LABEL[r.level], kind: KIND_LABEL[r.kind], evidence: EVIDENCE_LABEL[r.evidence] })) as unknown as Record<string, unknown>[];
  exportRows(kind, rows, ["url", ...REPO_EXPORT_COLS], { source: "Copilot Plugin Finder", generated_at: generated, filters: location.hash });
}

function searchHit(r: Repo): boolean {
  return searchHits === null || searchHits.has(r.id);
}

function applySearch(): void {
  const q = filters.q.trim();
  if (!q || !repoSearch) { searchHits = null; return; }
  const res = repoSearch.search(q, { prefix: true, fuzzy: 0.15, combineWith: "AND" });
  searchHits = new Set(res.map((x) => x.id as number));
}

let applyTimer: number | undefined;
function applyRepos(immediate = false): void {
  window.clearTimeout(applyTimer);
  const run = () => {
    applySearch();
    const rows = repos.filter((r) => searchHit(r) && passes(r, filters));
    repoGrid.setData(rows);
    countEl.textContent = `${rows.length.toLocaleString()} of ${repos.length.toLocaleString()} repositories`;
    charts.update(rows);
    renderSidebar();
    pushHash();
  };
  if (immediate) run(); else applyTimer = window.setTimeout(run, 120);
}

function onChartAction(a: ChartAction): void {
  switch (a.type) {
    case "created": filters.createdFrom = a.from; filters.createdTo = a.to; break;
    case "stars": filters.starsMin = a.min; filters.starsMax = a.max; break;
    case "owner": filters.q = a.owner + "/"; break;
    case "exec": filters.exec = new Set([a.value]); break;
  }
  applyRepos(true);
}

// ---- sidebar ----
function chipFacet(title: string, key: FacetKey, counts: Map<string, number>, label: (v: string) => string, limit = 10, selected?: Set<string | number>): HTMLElement {
  const sel = selected ?? (filters[key] as Set<string | number>);
  const entries = [...counts.entries()].sort((a, b) => b[1] - a[1]);
  const wrap = el("div", { class: "facet" });
  const clear = el("button", { type: "button" }, "clear");
  clear.addEventListener("click", () => { sel.clear(); applyRepos(true); });
  wrap.append(el("h3", {}, title, sel.size ? clear : ""));
  const chips = el("div", { class: "chips", role: "group", "aria-label": title });
  const shown = entries.filter((e, i) => i < limit || sel.has(e[0]) || sel.has(Number(e[0])));
  for (const [v, n] of shown) {
    const val = key === "level" || key === "evidence" ? Number(v) : v;
    const on = sel.has(val);
    const chip = el("button", { class: "chip", type: "button", "aria-pressed": String(on) }, label(v), el("span", { class: "n" }, n.toLocaleString()));
    chip.addEventListener("click", () => { if (on) sel.delete(val); else sel.add(val); applyRepos(true); });
    chips.append(chip);
  }
  if (entries.length > shown.length) {
    const more = el("button", { class: "chip", type: "button" }, `+${entries.length - shown.length} more`);
    more.addEventListener("click", () => { wrap.replaceWith(chipFacet(title, key, counts, label, 1000, selected)); });
    chips.append(more);
  }
  wrap.append(chips);
  return wrap;
}

function tri(title: string, key: "archived" | "template" | "fork", labels: [string, string, string]): HTMLElement {
  const wrap = el("div", { class: "facet" }, el("h3", {}, title));
  const chips = el("div", { class: "chips" });
  (["any", "no", "yes"] as const).forEach((v, i) => {
    const c = el("button", { class: "chip", type: "button", "aria-pressed": String(filters[key] === v) }, labels[i]);
    c.addEventListener("click", () => { filters[key] = v; applyRepos(true); });
    chips.append(c);
  });
  wrap.append(chips);
  return wrap;
}

function check(label: string, get: () => boolean, set: (v: boolean) => void): HTMLElement {
  const id = "ck-" + label.replace(/\W+/g, "-");
  const input = el("input", { type: "checkbox", id }) as HTMLInputElement;
  input.checked = get();
  input.addEventListener("change", () => { set(input.checked); applyRepos(true); });
  return el("label", { class: "checkrow", for: id }, input, label);
}

function numInput(placeholder: string, get: () => number | null, set: (v: number | null) => void): HTMLInputElement {
  const i = el("input", { type: "number", min: 0, placeholder, "aria-label": placeholder }) as HTMLInputElement;
  const v = get();
  i.value = v === null ? "" : String(v);
  i.addEventListener("change", () => { set(i.value === "" ? null : Number(i.value)); applyRepos(true); });
  return i;
}

function dateInput(label: string, get: () => string, set: (v: string) => void): HTMLInputElement {
  const i = el("input", { type: "date", "aria-label": label }) as HTMLInputElement;
  i.value = get().slice(0, 10);
  i.addEventListener("change", () => { set(i.value); applyRepos(true); });
  return i;
}

function renderSidebar(): void {
  const counts = facetCounts(repos, filters, searchHit);
  const q = el("input", { class: "search", type: "search", placeholder: "Search name, description, topics, marketplace…", "aria-label": "Search repositories" }) as HTMLInputElement;
  q.value = filters.q;
  q.addEventListener("input", () => { filters.q = q.value; applyRepos(); });
  const parts: HTMLElement[] = [q];
  parts.push(chipFacet("Level", "level", counts.level, (v) => LEVEL_LABEL[Number(v)]));
  parts.push(chipFacet("Kind", "kind", counts.kind, (v) => KIND_LABEL[v] ?? v));
  parts.push(chipFacet("Format", "format", counts.format, (v) => v || "(unknown)"));
  parts.push(chipFacet("Runs code", "exec", counts.exec, (v) => (v === "copilot-components" ? "copilot dir" : v)));
  parts.push(chipFacet("Evidence", "evidence", counts.evidence, (v) => EVIDENCE_LABEL[Number(v)]));
  parts.push(chipFacet("Owner type", "ownerType", counts.ownerType, (v) => (v === "O" ? "organisation" : "user")));
  parts.push(chipFacet("Language", "language", counts.language, (v) => v, 8));
  parts.push(chipFacet("License", "license", counts.license, (v) => v, 6));
  const stars = el("div", { class: "facet" }, el("h3", {}, "Stars"), el("div", { class: "range" },
    numInput("min", () => filters.starsMin, (v) => (filters.starsMin = v)), "–", numInput("max", () => filters.starsMax, (v) => (filters.starsMax = v))));
  parts.push(stars);
  parts.push(el("div", { class: "facet" }, el("h3", {}, "Minimums"), el("div", { class: "range" },
    numInput("plugins ≥", () => filters.pluginsMin, (v) => (filters.pluginsMin = v)), numInput("refs ≥", () => filters.refMin, (v) => (filters.refMin = v)))));
  parts.push(el("div", { class: "facet" }, el("h3", {}, "Created between"), el("div", { class: "range" },
    dateInput("created from", () => filters.createdFrom, (v) => (filters.createdFrom = v)), dateInput("created to", () => filters.createdTo, (v) => (filters.createdTo = v)))));
  const pw = el("div", { class: "facet" }, el("h3", {}, "Last commit within"));
  const chips = el("div", { class: "chips" });
  for (const [l, d] of [["any", null], ["30 d", 30], ["90 d", 90], ["1 y", 365]] as [string, number | null][]) {
    const c = el("button", { class: "chip", type: "button", "aria-pressed": String(filters.pushedWithin === d) }, l);
    c.addEventListener("click", () => { filters.pushedWithin = d; applyRepos(true); });
    chips.append(c);
  }
  pw.append(chips);
  parts.push(pw);
  parts.push(tri("Archived", "archived", ["any", "active only", "archived only"]));
  parts.push(tri("Template repo", "template", ["any", "no", "yes"]));
  parts.push(tri("Fork", "fork", ["any", "sources only", "forks only"]));
  const valid = el("div", { class: "facet" }, el("h3", {}, "Validation"));
  const vchips = el("div", { class: "chips" });
  for (const [l, v] of [["any", "any"], ["valid, no warnings", "valid"], ["has warnings", "warn"]] as const) {
    const c = el("button", { class: "chip", type: "button", "aria-pressed": String(filters.valid === v) }, l);
    c.addEventListener("click", () => { filters.valid = v; applyRepos(true); });
    vchips.append(c);
  }
  valid.append(vchips);
  parts.push(valid);
  parts.push(el("div", { class: "facet" }, el("h3", {}, "More"),
    check("Listed by awesome-copilot / copilot-plugins", () => filters.seed, (v) => (filters.seed = v)),
    check("Dual format (.github/plugin + .claude-plugin)", () => filters.dual, (v) => (filters.dual = v)),
    check("Copilot-specific components", () => filters.copspec, (v) => (filters.copspec = v)),
    check("Show non-canonical copies", () => filters.copies, (v) => (filters.copies = v)),
    check("Diverged forks only", () => filters.diverged, (v) => (filters.diverged = v)),
  ));
  if (filters.topic) {
    const t = el("div", { class: "facet" }, el("h3", {}, "Topic"), el("div", { class: "chips" }));
    const c = el("button", { class: "chip", type: "button", "aria-pressed": "true" }, filters.topic, " ✕");
    c.addEventListener("click", () => { filters.topic = ""; applyRepos(true); });
    t.querySelector(".chips")!.append(c);
    parts.push(t);
  }
  const active = document.activeElement === sidebar.querySelector(".search");
  const pos = (sidebar.querySelector(".search") as HTMLInputElement | null)?.selectionStart ?? null;
  sidebar.replaceChildren(...parts);
  if (active) { q.focus(); if (pos !== null) q.setSelectionRange(pos, pos); }
}

// ---------------- plugins view ----------------
let pluginGrid: Grid<Plugin & { id: number }> | null = null;
let pluginSidebar: HTMLElement;
let pluginCount: HTMLElement;
let pluginRows: (Plugin & { id: number })[] = [];

function buildPluginsView(): HTMLElement {
  pluginSidebar = el("aside", { class: "sidebar", "aria-label": "Plugin filters" });
  pluginCount = el("span", { class: "count" });
  pluginGrid = new Grid<Plugin & { id: number }>({
    ariaLabel: "Plugins",
    rowHeight: 42,
    initialSort: [{ id: "stars", desc: true }],
    onRowClick: (p) => { const r = repos.find((x) => x.id === p.repo_id); if (r) openRepo(r); },
    columns: [
      { id: "name", header: "Plugin", width: "minmax(220px,1.4fr)", accessor: (p) => p.name, cell: (p) => { const n = el("div", { class: "name" }, clean(p.name, 80)); n.append(el("small", {}, clean(p.desc ?? "", 120))); return n; } },
      { id: "repo", header: "Repository", width: "minmax(200px,1fr)", accessor: (p) => p.repo, cell: (p) => link(ghRepo(p.repo), p.repo) },
      { id: "path", header: "Path", width: "150px", accessor: (p) => p.path ?? "", cell: (p) => (p.path && p.path !== "." ? p.path : "") },
      { id: "level", header: "Level", width: "110px", accessor: (p) => p.level, num: true, cell: (p) => badge(p.level === 0 ? "Copilot" : "Claude fmt", p.level === 0 ? "copilot" : "claude") },
      { id: "format", header: "Format", width: "120px", accessor: (p) => p.format ?? "", cell: (p) => p.format ?? "" },
      { id: "version", header: "Version", width: "80px", accessor: (p) => p.version ?? "", cell: (p) => clean(p.version ?? "", 16) },
      { id: "stars", header: "Repo stars", width: "90px", accessor: (p) => p.stars, num: true, cell: (p) => fmtNum(p.stars) },
      { id: "distributors", header: "Listed by", width: "80px", accessor: (p) => p.distributors, num: true, cell: (p) => String(p.distributors || "") },
      { id: "exec", header: "Runs code", width: "150px", accessor: (p) => p.exec, cell: (p) => { const d = el("div"); for (const x of p.exec ? p.exec.split(",") : []) d.append(badge(x, "exec")); return d; } },
      { id: "category", header: "Category", width: "120px", accessor: (p) => p.category ?? "", cell: (p) => clean(p.category ?? "", 30) },
    ],
  });
  const csv = el("button", { class: "btn small", type: "button" }, "Export CSV");
  csv.addEventListener("click", () => exportRows("csv", pluginGrid!.sortedRows() as unknown as Record<string, unknown>[], ["name", "version", "desc", "repo", "path", "stars", "level", "format", "source_kind", "exec", "category", "distributors", "seed"], { source: "Copilot Plugin Finder plugins", generated_at: generated }));
  const tb = el("div", { class: "toolbar" }, pluginCount, el("span", { class: "spacer" }), csv);
  return el("div", { class: "view" }, pluginSidebar, el("div", { class: "content" }, tb, pluginGrid.root));
}

function pluginPasses(p: Plugin, skip?: string): boolean {
  if (skip !== "level" && pluginFilters.level.size && !pluginFilters.level.has(p.level)) return false;
  if (skip !== "format" && pluginFilters.format.size && !pluginFilters.format.has(p.format ?? "")) return false;
  if (skip !== "exec" && pluginFilters.exec.size) { const ex = p.exec ? p.exec.split(",") : []; if (![...pluginFilters.exec].some((e) => (e === "(none)" ? !ex.length : ex.includes(e)))) return false; }
  if (pluginFilters.seedOnly && !p.seed) return false;
  if (pluginFilters.distributed && !p.distributors) return false;
  return true;
}

function applyPlugins(): void {
  if (!pluginGrid) return;
  let hits: Set<number> | null = null;
  const q = pluginFilters.q.trim();
  if (q && pluginSearch) hits = new Set(pluginSearch.search(q, { prefix: true, fuzzy: 0.15, combineWith: "AND" }).map((x) => x.id as number));
  const rows = pluginRows.filter((p) => (hits === null || hits.has(p.id)) && pluginPasses(p));
  pluginGrid.setData(rows);
  pluginCount.textContent = `${rows.length.toLocaleString()} of ${pluginRows.length.toLocaleString()} plugins`;
  // sidebar
  const count = (key: string, pick: (p: Plugin) => string[]) => { const m = new Map<string, number>(); for (const p of pluginRows) { if (hits !== null && !hits.has(p.id)) continue; if (!pluginPasses(p, key)) continue; for (const v of pick(p)) m.set(v, (m.get(v) ?? 0) + 1); } return [...m.entries()].sort((a, b) => b[1] - a[1]); };
  const facet = (title: string, key: string, entries: [string, number][], sel: Set<string | number>, label: (v: string) => string, numeric = false) => {
    const wrap = el("div", { class: "facet" }, el("h3", {}, title));
    const chips = el("div", { class: "chips" });
    for (const [v, n] of entries.slice(0, 10)) {
      const val = numeric ? Number(v) : v;
      const on = sel.has(val);
      const c = el("button", { class: "chip", type: "button", "aria-pressed": String(on) }, label(v), el("span", { class: "n" }, n.toLocaleString()));
      c.addEventListener("click", () => { if (on) sel.delete(val); else sel.add(val); applyPlugins(); });
      chips.append(c);
    }
    wrap.append(chips);
    void key;
    return wrap;
  };
  const qi = el("input", { class: "search", type: "search", placeholder: "Search plugin name, description, repository…", "aria-label": "Search plugins" }) as HTMLInputElement;
  qi.value = pluginFilters.q;
  let t: number | undefined;
  qi.addEventListener("input", () => { pluginFilters.q = qi.value; window.clearTimeout(t); t = window.setTimeout(applyPlugins, 150); });
  const focused = document.activeElement === pluginSidebar.querySelector(".search");
  pluginSidebar.replaceChildren(
    qi,
    facet("Level", "level", count("level", (p) => [String(p.level)]), pluginFilters.level, (v) => LEVEL_LABEL[Number(v)], true),
    facet("Format", "format", count("format", (p) => [p.format ?? ""]), pluginFilters.format, (v) => v || "(unknown)"),
    facet("Runs code", "exec", count("exec", (p) => (p.exec ? p.exec.split(",") : ["(none)"])), pluginFilters.exec, (v) => v),
    el("div", { class: "facet" }, el("h3", {}, "More"),
      (() => { const i = el("input", { type: "checkbox", id: "pk-seed" }) as HTMLInputElement; i.checked = pluginFilters.seedOnly; i.addEventListener("change", () => { pluginFilters.seedOnly = i.checked; applyPlugins(); }); return el("label", { class: "checkrow", for: "pk-seed" }, i, "Home repo listed by a seed marketplace"); })(),
      (() => { const i = el("input", { type: "checkbox", id: "pk-dist" }) as HTMLInputElement; i.checked = pluginFilters.distributed; i.addEventListener("change", () => { pluginFilters.distributed = i.checked; applyPlugins(); }); return el("label", { class: "checkrow", for: "pk-dist" }, i, "Listed by at least one other marketplace"); })(),
    ),
  );
  if (focused) { qi.focus(); qi.setSelectionRange(qi.value.length, qi.value.length); }
}

async function ensurePlugins(): Promise<void> {
  if (plugins) return;
  plugins = await loadPlugins();
  pluginRows = plugins.map((p, i) => ({ ...p, id: i }));
  pluginSearch = new MiniSearch<Plugin & { id: number }>({ fields: ["name", "desc", "repo", "category"], storeFields: [], searchOptions: { boost: { name: 3 } } });
  pluginSearch.addAll(pluginRows);
}

// ---------------- shell ----------------
function pushHash(): void {
  const h = toHash(tab, filters, sortKey);
  if (location.hash !== h) history.replaceState(null, "", h);
}

function parseSort(s: string): SortingState {
  return s ? s.split(",").filter(Boolean).map((x) => ({ id: x.replace(/^-/, ""), desc: x.startsWith("-") })) : [{ id: "stars", desc: true }];
}

const views: Record<string, HTMLElement> = {};
async function showTab(name: string): Promise<void> {
  tab = name;
  closeDetail();
  document.querySelectorAll<HTMLButtonElement>(".tab").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  if (name === "plugins") {
    if (!views.plugins) views.plugins = buildPluginsView();
    main().replaceChildren(views.plugins);
    await ensurePlugins();
    applyPlugins();
  } else if (name === "about") {
    main().replaceChildren(renderAbout(meta, generated));
  } else {
    main().replaceChildren(views.repos);
    applyRepos(true);
  }
  pushHash();
}

async function boot(): Promise<void> {
  const tagline = document.getElementById("tagline")!;
  try {
    const [r, m] = await Promise.all([loadRepos(), loadMeta().catch(() => null)]);
    repos = r.repos;
    generated = r.generated;
    meta = m;
  } catch (e) {
    tagline.textContent = `Failed to load data: ${(e as Error).message}`;
    return;
  }
  for (const x of repos) byName.set(x.name.toLowerCase(), x);
  repoSearch = new MiniSearch<Repo>({ fields: ["name", "desc", "mk_name", "topics"], storeFields: [], extractField: (doc, f) => (f === "topics" ? doc.topics.join(" ") : String((doc as unknown as Record<string, unknown>)[f] ?? "")), searchOptions: { boost: { name: 3, mk_name: 2 } } });
  repoSearch.addAll(repos);
  const canon = repos.filter((x) => x.canonical).length;
  tagline.textContent = `${canon.toLocaleString()} canonical repositories (${repos.length.toLocaleString()} including copies) that GitHub Copilot can install as plugins or register as marketplaces.`;
  const badgeEl = document.getElementById("scanbadge")!;
  badgeEl.textContent = `data ${generated.slice(0, 16).replace("T", " ")} UTC${meta?.golden_recall !== null && meta?.golden_recall !== undefined ? ` · golden recall ${(meta.golden_recall * 100).toFixed(0)}%` : ""}`;
  views.repos = buildReposView();
  const st = fromHash(location.hash);
  filters = st.f;
  sortKey = st.sort;
  repoGrid.setSort(parseSort(st.sort));
  document.querySelectorAll<HTMLButtonElement>(".tab").forEach((b) => b.addEventListener("click", () => void showTab(b.dataset.tab!)));
  window.addEventListener("hashchange", () => { const s = fromHash(location.hash); if (s.tab !== tab) void showTab(s.tab); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDetail(); });
  await showTab(st.tab);
}

void boot();
