// Tiny safe DOM helpers: everything is textContent, links are https-only, no innerHTML anywhere.

export function el<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Record<string, string | number | boolean | null | undefined> = {}, ...children: (Node | string | null | undefined | false)[]): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") e.className = String(v);
    else if (k === "text") e.textContent = String(v);
    else e.setAttribute(k, String(v));
  }
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    e.append(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return e;
}

const BIDI = /[​-‏‪-‮⁦-⁩]/g;
export function clean(s: string | null | undefined, max = 400): string {
  if (!s) return "";
  const t = String(s).replace(BIDI, "");
  return t.length > max ? t.slice(0, max - 1) + "…" : t;
}

export function link(href: string, text: string, cls?: string): HTMLElement {
  let safe = "#";
  try {
    const u = new URL(href);
    if (u.protocol === "https:") safe = u.toString();
  } catch { /* keep # */ }
  const a = el("a", { href: safe, target: "_blank", rel: "noopener noreferrer nofollow", class: cls }, clean(text, 200));
  return a;
}

export const ghRepo = (name: string) => `https://github.com/${name}`;
export const ghBlob = (name: string, ref: string | null, path: string) => `https://github.com/${name}/blob/${encodeURIComponent(ref || "HEAD")}/${path.split("/").map(encodeURIComponent).join("/")}`;

export function badge(text: string, cls = ""): HTMLElement {
  return el("span", { class: `badge ${cls}`.trim() }, text);
}

export function fmtNum(n: number | null | undefined): string {
  if (n === null || n === undefined) return "";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e4) return (n / 1e3).toFixed(0) + "k";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "k";
  return String(n);
}

export function copyButton(text: string): HTMLElement {
  const b = el("button", { class: "btn small", type: "button", "aria-label": "Copy to clipboard" }, "Copy");
  b.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(text);
      toast("Copied");
    } catch {
      toast("Copy failed");
    }
  });
  return b;
}

let toastTimer: number | undefined;
export function toast(msg: string): void {
  let t = document.querySelector<HTMLElement>(".toast");
  if (!t) {
    t = el("div", { class: "toast", role: "status" });
    document.body.append(t);
  }
  t.textContent = msg;
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => t?.remove(), 1600);
}
