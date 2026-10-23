// CSV / JSON export of the current view, with spreadsheet formula-injection neutralised.

function csvCell(v: unknown): string {
  if (v === null || v === undefined) return "";
  let s = Array.isArray(v) ? v.join("|") : String(v);
  if (/^[=+\-@\t\r]/.test(s)) s = "'" + s; // neutralise =, +, -, @ at the start of a cell
  if (/[",\n\r]/.test(s)) s = '"' + s.replace(/"/g, '""') + '"';
  return s;
}

export function toCSV(rows: Record<string, unknown>[], columns: string[]): string {
  const lines = [columns.join(",")];
  for (const r of rows) lines.push(columns.map((c) => csvCell(r[c])).join(","));
  return lines.join("\r\n");
}

export function download(name: string, content: string, type: string): void {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export function exportRows(kind: "csv" | "json", rows: Record<string, unknown>[], columns: string[], context: Record<string, unknown>): void {
  const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  if (kind === "csv") {
    download(`cpf-${stamp}.csv`, toCSV(rows, columns), "text/csv;charset=utf-8");
  } else {
    download(`cpf-${stamp}.json`, JSON.stringify({ ...context, exported_at: new Date().toISOString(), count: rows.length, rows }, null, 1), "application/json");
  }
}
