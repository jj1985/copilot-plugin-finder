// Loads the columnar JSON written by `cpf site` and turns it into typed rows.

export interface Repo {
  id: number;
  name: string;
  owner: string;
  owner_type: string; // U | O
  desc: string | null;
  stars: number;
  forks: number;
  created: string;
  committed: string;
  pushed: string;
  is_fork: number;
  parent: string | null;
  archived: number;
  template: number;
  language: string | null;
  license: string | null;
  kind: string; // m | p | b
  level: number; // 0 copilot-authored, 1 claude-format
  evidence: number; // 0 root, 1 nested, 2 declared
  format: string | null;
  dual: number;
  copspec: number;
  exec: string; // comma list
  mk_path: string | null;
  pl_path: string | null;
  mk_name: string | null;
  plugins: number;
  ext_plugins: number;
  valid: number | null;
  nwarn: number;
  cluster: number | null;
  canonical: number;
  network: number | null;
  copies: number | null;
  diverged: number;
  ref_mk: number;
  ref_set: number;
  seed: string | null;
  topics: string[];
  shard: number;
  head: string | null;
}

export interface Plugin {
  name: string;
  version: string | null;
  desc: string | null;
  repo_id: number;
  repo: string;
  stars: number;
  level: number;
  format: string | null;
  source_kind: string;
  path: string | null;
  exec: string;
  category: string | null;
  distributors: number;
  seed: string | null;
  canonical: number;
}

export interface Meta {
  generated_at: string;
  report_url: string;
  repos_active: number;
  repos_canonical: number;
  plugins: number;
  counts: Record<string, number>;
  by_level: Record<string, number>;
  clusters: number;
  diverged_forks: number;
  adopters: number;
  golden_recall: number | null;
  last_scan: { id: number; kind: string; started: string; finished: string | null; status: string } | null;
  last_full_scan: { id: number; started: string; finished: string | null; status: string; repos_seen: number; repos_verified: number } | null;
  slices_incomplete: number;
  markers: { marker_id: string; repos: number }[];
  requests: Record<string, number> | null;
}

export interface Detail {
  id: number; name: string; desc: string | null; homepage: string | null; readme: string | null; readme_name: string | null;
  default_branch: string | null; head: string | null;
  marketplace: { name: string; owner: string | null; desc: string | null; version: string | null; plugin_root: string | null } | null;
  plugin: { name: string; version: string | null; desc: string | null } | null;
  mk_path: string | null; pl_path: string | null; shadowed: string[]; warnings: string[];
  markers: { marker: string; path: string }[];
  plugins: { name: string; version: string | null; desc: string | null; source_kind: string; source_repo: string | null; path: string | null; ref: string | null; pinned: number; format: string | null; exec: string[]; category: string | null; strict: number | null }[];
  plugins_total: number; topics: string[];
  cluster: { id: number | null; canonical: number; network: number | null; copies: number | null; members: { name: string; stars: number; fork: number; canonical: number; diverged: number }[]; edges: { other: string; signal: string }[] };
  listed_in: { marketplace: string; entry: string }[];
  adopters: { repo: string; stars: number }[];
  adopter_count: number; seed: string | null; first_seen: string; last_verified: string | null;
  license: string | null; language: string | null; latest_release: string | null; parent: string | null; template: string | null; diverged: number;
  surfaces: Record<string, string>;
}

interface Columnar { columns: string[]; rows: unknown[][]; dicts?: Record<string, string[]>; generated_at?: string }

function decode<T>(c: Columnar, dictCols: Record<string, string>): T[] {
  const idx = Object.fromEntries(c.columns.map((n, i) => [n, i]));
  const out: T[] = [];
  for (const r of c.rows) {
    const o: Record<string, unknown> = {};
    for (const [n, i] of Object.entries(idx)) {
      let v = r[i];
      const d = dictCols[n];
      if (d) v = typeof v === "number" && v >= 0 ? c.dicts![d][v] : null;
      o[n] = v;
    }
    out.push(o as T);
  }
  return out;
}

async function getJSON<T>(path: string): Promise<T> {
  const res = await fetch(path, { cache: "no-cache" });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return (await res.json()) as T;
}

export async function loadRepos(): Promise<{ repos: Repo[]; generated: string }> {
  const c = await getJSON<Columnar>("data/repos.json");
  return { repos: decode<Repo>(c, { owner: "owner", language: "language", license: "license" }), generated: c.generated_at ?? "" };
}

export async function loadPlugins(): Promise<Plugin[]> {
  const c = await getJSON<Columnar>("data/plugins.json");
  return decode<Plugin>(c, {});
}

export const loadMeta = () => getJSON<Meta>("data/meta.json");

const shardCache = new Map<number, Promise<Record<string, Detail>>>();
export async function loadDetail(repo: Repo): Promise<Detail | null> {
  if (!shardCache.has(repo.shard)) {
    shardCache.set(repo.shard, getJSON<Record<string, Detail>>(`data/detail/${String(repo.shard).padStart(3, "0")}.json`));
  }
  const shard = await shardCache.get(repo.shard)!;
  return shard[String(repo.id)] ?? null;
}

export const LEVEL_LABEL = ["Copilot-authored", "Copilot-installable (Claude format)"];
export const KIND_LABEL: Record<string, string> = { m: "marketplace", p: "plugin", b: "marketplace + plugin" };
export const EVIDENCE_LABEL = ["verified at root", "verified nested", "declared only"];
