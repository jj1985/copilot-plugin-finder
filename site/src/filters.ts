// Filter state, predicate and facet counting for the Repositories view.
import type { Repo } from "./data";

export interface FilterState {
  q: string;
  level: Set<number>;
  kind: Set<string>;
  format: Set<string>;
  evidence: Set<number>;
  ownerType: Set<string>;
  language: Set<string>;
  license: Set<string>;
  exec: Set<string>;
  seed: boolean;
  dual: boolean;
  copspec: boolean;
  archived: "any" | "no" | "yes";
  template: "any" | "no" | "yes";
  fork: "any" | "no" | "yes";
  copies: boolean; // show non-canonical copies
  diverged: boolean; // only diverged forks
  valid: "any" | "valid" | "warn";
  starsMin: number | null;
  starsMax: number | null;
  refMin: number | null;
  pluginsMin: number | null;
  createdFrom: string;
  createdTo: string;
  pushedWithin: number | null; // days
  topic: string;
}

export function defaultFilters(): FilterState {
  return {
    q: "", level: new Set([0]), kind: new Set(), format: new Set(), evidence: new Set(), ownerType: new Set(),
    language: new Set(), license: new Set(), exec: new Set(), seed: false, dual: false, copspec: false,
    archived: "any", template: "any", fork: "any", copies: false, diverged: false, valid: "any",
    starsMin: null, starsMax: null, refMin: null, pluginsMin: null, createdFrom: "", createdTo: "", pushedWithin: null, topic: "",
  };
}

export type FacetKey = "level" | "kind" | "format" | "evidence" | "ownerType" | "language" | "license" | "exec";

const DAY = 86400000;

function daysAgo(iso: string): number {
  if (!iso) return Infinity;
  return (Date.now() - Date.parse(iso)) / DAY;
}

/** Predicate for all facets except `skip` (used for facet counts) and except the search, which is applied separately. */
export function passes(r: Repo, f: FilterState, skip?: FacetKey): boolean {
  if (!f.copies && !r.canonical) return false;
  if (f.diverged && !r.diverged) return false;
  if (skip !== "level" && f.level.size && !f.level.has(r.level)) return false;
  if (skip !== "kind" && f.kind.size && !f.kind.has(r.kind)) return false;
  if (skip !== "format" && f.format.size && !f.format.has(r.format ?? "")) return false;
  if (skip !== "evidence" && f.evidence.size && !f.evidence.has(r.evidence)) return false;
  if (skip !== "ownerType" && f.ownerType.size && !f.ownerType.has(r.owner_type)) return false;
  if (skip !== "language" && f.language.size && !f.language.has(r.language ?? "(none)")) return false;
  if (skip !== "license" && f.license.size && !f.license.has(r.license ?? "(none)")) return false;
  if (skip !== "exec" && f.exec.size) {
    const ex = r.exec ? r.exec.split(",") : [];
    if (f.exec.has("(none)") ? ex.length !== 0 || f.exec.size > 1 && ![...f.exec].some((e) => ex.includes(e)) : ![...f.exec].some((e) => ex.includes(e))) return false;
  }
  if (f.seed && !r.seed) return false;
  if (f.dual && !r.dual) return false;
  if (f.copspec && !r.copspec) return false;
  if (f.archived !== "any" && Boolean(r.archived) !== (f.archived === "yes")) return false;
  if (f.template !== "any" && Boolean(r.template) !== (f.template === "yes")) return false;
  if (f.fork !== "any" && Boolean(r.is_fork) !== (f.fork === "yes")) return false;
  if (f.valid === "valid" && (r.valid !== 1 || r.nwarn > 0)) return false;
  if (f.valid === "warn" && r.nwarn === 0) return false;
  if (f.starsMin !== null && r.stars < f.starsMin) return false;
  if (f.starsMax !== null && r.stars > f.starsMax) return false;
  if (f.refMin !== null && r.ref_mk + r.ref_set < f.refMin) return false;
  if (f.pluginsMin !== null && r.plugins < f.pluginsMin) return false;
  if (f.createdFrom && r.created < f.createdFrom) return false;
  if (f.createdTo && r.created > f.createdTo) return false;
  if (f.pushedWithin !== null && daysAgo(r.committed || r.pushed) > f.pushedWithin) return false;
  if (f.topic && !r.topics.includes(f.topic)) return false;
  return true;
}

export function facetCounts(rows: Repo[], f: FilterState, searchHit: (r: Repo) => boolean): Record<FacetKey, Map<string, number>> {
  const keys: FacetKey[] = ["level", "kind", "format", "evidence", "ownerType", "language", "license", "exec"];
  const out = Object.fromEntries(keys.map((k) => [k, new Map<string, number>()])) as Record<FacetKey, Map<string, number>>;
  const bump = (m: Map<string, number>, k: string) => m.set(k, (m.get(k) ?? 0) + 1);
  for (const r of rows) {
    if (!searchHit(r)) continue;
    for (const k of keys) {
      if (!passes(r, f, k)) continue;
      switch (k) {
        case "level": bump(out.level, String(r.level)); break;
        case "kind": bump(out.kind, r.kind); break;
        case "format": bump(out.format, r.format ?? ""); break;
        case "evidence": bump(out.evidence, String(r.evidence)); break;
        case "ownerType": bump(out.ownerType, r.owner_type); break;
        case "language": bump(out.language, r.language ?? "(none)"); break;
        case "license": bump(out.license, r.license ?? "(none)"); break;
        case "exec": {
          const ex = r.exec ? r.exec.split(",") : [];
          if (!ex.length) bump(out.exec, "(none)");
          for (const e of ex) bump(out.exec, e);
        }
      }
    }
  }
  return out;
}

// ---- URL hash (versioned) ----

const SET_KEYS = ["level", "kind", "format", "evidence", "ownerType", "language", "license", "exec"] as const;

export function toHash(tab: string, f: FilterState, sort: string): string {
  const p = new URLSearchParams();
  p.set("v", "1");
  p.set("tab", tab);
  if (f.q) p.set("q", f.q);
  for (const k of SET_KEYS) {
    const s = f[k] as Set<string | number>;
    if (k === "level" ? !(s.size === 1 && s.has(0)) : s.size) p.set(k, [...s].join("|"));
  }
  for (const k of ["seed", "dual", "copspec", "copies", "diverged"] as const) if (f[k]) p.set(k, "1");
  for (const k of ["archived", "template", "fork", "valid"] as const) if (f[k] !== "any") p.set(k, f[k]);
  for (const k of ["starsMin", "starsMax", "refMin", "pluginsMin", "pushedWithin"] as const) if (f[k] !== null) p.set(k, String(f[k]));
  for (const k of ["createdFrom", "createdTo", "topic"] as const) if (f[k]) p.set(k, f[k]);
  if (sort) p.set("sort", sort);
  return "#" + p.toString();
}

export function fromHash(hash: string): { tab: string; f: FilterState; sort: string } {
  const f = defaultFilters();
  const p = new URLSearchParams(hash.replace(/^#/, ""));
  const tab = p.get("tab") ?? "repos";
  if (p.get("v") !== "1") return { tab, f, sort: "" };
  f.q = p.get("q") ?? "";
  for (const k of SET_KEYS) {
    const v = p.get(k);
    if (v === null) continue;
    const parts = v === "" ? [] : v.split("|");
    const target = f as unknown as Record<string, unknown>;
    target[k] = k === "level" || k === "evidence" ? new Set<number>(parts.map(Number)) : new Set<string>(parts);
  }
  for (const k of ["seed", "dual", "copspec", "copies", "diverged"] as const) f[k] = p.get(k) === "1";
  for (const k of ["archived", "template", "fork"] as const) { const v = p.get(k); if (v === "yes" || v === "no") f[k] = v; }
  { const v = p.get("valid"); if (v === "valid" || v === "warn") f.valid = v; }
  for (const k of ["starsMin", "starsMax", "refMin", "pluginsMin", "pushedWithin"] as const) { const v = p.get(k); if (v !== null && v !== "" && !Number.isNaN(Number(v))) f[k] = Number(v); }
  for (const k of ["createdFrom", "createdTo", "topic"] as const) f[k] = p.get(k) ?? "";
  return { tab, f, sort: p.get("sort") ?? "" };
}
