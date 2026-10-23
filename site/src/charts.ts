// Four cross-filtering charts for the Repositories view (Chart.js, tree-shaken).
import { BarController, BarElement, CategoryScale, Chart, Legend, LinearScale, Tooltip } from "chart.js";
import type { Repo } from "./data";
import { el } from "./dom";

Chart.register(BarController, BarElement, CategoryScale, LinearScale, Tooltip, Legend);

export type ChartAction =
  | { type: "created"; from: string; to: string }
  | { type: "stars"; min: number; max: number | null }
  | { type: "owner"; owner: string }
  | { type: "exec"; value: string };

const STAR_BUCKETS: { label: string; min: number; max: number | null }[] = [
  { label: "0", min: 0, max: 0 },
  { label: "1–9", min: 1, max: 9 },
  { label: "10–99", min: 10, max: 99 },
  { label: "100–999", min: 100, max: 999 },
  { label: "1k–9.9k", min: 1000, max: 9999 },
  { label: "10k+", min: 10000, max: null },
];
const EXEC_KEYS = ["hooks", "mcp", "lsp", "extensions", "copilot-components", "scripts", "(none)"];

const css = (v: string) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

export class Charts {
  readonly root: HTMLElement;
  private charts: Chart[] = [];
  private canvases: HTMLCanvasElement[] = [];

  constructor(private onAction: (a: ChartAction) => void) {
    const titles = ["Repos by creation month (stacked by level)", "Stars distribution", "Top owners", "Components that run code"];
    this.root = el("div", { class: "charts" });
    for (const t of titles) {
      const c = el("canvas", { role: "img", "aria-label": t });
      this.canvases.push(c);
      this.root.append(el("div", { class: "chart" }, el("h4", {}, t), c));
    }
  }

  update(rows: Repo[]): void {
    for (const c of this.charts) c.destroy();
    this.charts = [];
    const fg = css("--muted") || "#666";
    const copilot = css("--copilot") || "#2563eb";
    const claude = css("--claude") || "#d97706";
    const base = {
      responsive: true,
      maintainAspectRatio: false,
      animation: false as const,
      plugins: { legend: { display: false }, tooltip: { enabled: true } },
      scales: { x: { ticks: { color: fg, maxRotation: 0, autoSkip: true, font: { size: 10 } }, grid: { display: false } }, y: { ticks: { color: fg, font: { size: 10 } }, grid: { color: "rgba(128,128,128,0.15)" } } },
    };

    // 1. created month, last 18 months + earlier
    const months: string[] = [];
    const d = new Date();
    d.setDate(1);
    for (let i = 17; i >= 0; i--) {
      const m = new Date(d.getFullYear(), d.getMonth() - i, 1);
      months.push(`${m.getFullYear()}-${String(m.getMonth() + 1).padStart(2, "0")}`);
    }
    const labels1 = ["earlier", ...months];
    const s0 = new Array(labels1.length).fill(0);
    const s1 = new Array(labels1.length).fill(0);
    for (const r of rows) {
      const key = r.created.slice(0, 7);
      let i = months.indexOf(key);
      i = i < 0 ? (key < months[0] ? 0 : -1) : i + 1;
      if (i < 0) continue;
      (r.level === 0 ? s0 : s1)[i]++;
    }
    this.charts.push(new Chart(this.canvases[0], {
      type: "bar",
      data: { labels: labels1.map((l) => (l === "earlier" ? l : l.slice(2))), datasets: [
        { label: "Copilot-authored", data: s0, backgroundColor: copilot, stack: "a" },
        { label: "Claude format", data: s1, backgroundColor: claude, stack: "a" },
      ] },
      options: { ...base, plugins: { ...base.plugins, legend: { display: true, labels: { color: fg, boxWidth: 10, font: { size: 10 } } } },
        scales: { x: { ...base.scales.x, stacked: true }, y: { ...base.scales.y, stacked: true } },
        onClick: (_e, els) => {
          if (!els.length) return;
          const i = els[0].index;
          if (i === 0) this.onAction({ type: "created", from: "", to: months[0] + "-00" });
          else { const m = months[i - 1]; this.onAction({ type: "created", from: m + "-01", to: m + "-31" }); }
        } },
    }));

    // 2. stars buckets
    const sb = STAR_BUCKETS.map(() => 0);
    for (const r of rows) {
      const i = STAR_BUCKETS.findIndex((b) => r.stars >= b.min && (b.max === null || r.stars <= b.max));
      if (i >= 0) sb[i]++;
    }
    this.charts.push(new Chart(this.canvases[1], {
      type: "bar",
      data: { labels: STAR_BUCKETS.map((b) => b.label), datasets: [{ data: sb, backgroundColor: copilot }] },
      options: { ...base, onClick: (_e, els) => { if (els.length) { const b = STAR_BUCKETS[els[0].index]; this.onAction({ type: "stars", min: b.min, max: b.max }); } } },
    }));

    // 3. top owners
    const owners = new Map<string, number>();
    for (const r of rows) owners.set(r.owner, (owners.get(r.owner) ?? 0) + 1);
    const top = [...owners.entries()].sort((a, b) => b[1] - a[1]).slice(0, 7);
    this.charts.push(new Chart(this.canvases[2], {
      type: "bar",
      data: { labels: top.map((t) => t[0]), datasets: [{ data: top.map((t) => t[1]), backgroundColor: copilot }] },
      options: { ...base, indexAxis: "y", scales: { x: { ...base.scales.y }, y: { ...base.scales.x, ticks: { ...base.scales.x.ticks, autoSkip: false } } },
        onClick: (_e, els) => { if (els.length) this.onAction({ type: "owner", owner: top[els[0].index][0] }); } },
    }));

    // 4. executes-code mix
    const ex = EXEC_KEYS.map(() => 0);
    for (const r of rows) {
      const parts = r.exec ? r.exec.split(",") : [];
      if (!parts.length) ex[EXEC_KEYS.length - 1]++;
      for (const p of parts) { const i = EXEC_KEYS.indexOf(p); if (i >= 0) ex[i]++; }
    }
    this.charts.push(new Chart(this.canvases[3], {
      type: "bar",
      data: { labels: EXEC_KEYS.map((k) => (k === "copilot-components" ? "copilot dir" : k)), datasets: [{ data: ex, backgroundColor: claude }] },
      options: { ...base, onClick: (_e, els) => { if (els.length) this.onAction({ type: "exec", value: EXEC_KEYS[els[0].index] }); } },
    }));
  }
}
