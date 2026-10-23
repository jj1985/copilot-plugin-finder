// Sortable, virtualised data grid on TanStack table-core + virtual-core (framework-free).
import {
  createTable,
  getCoreRowModel,
  getSortedRowModel,
  type ColumnDef,
  type SortingState,
  type Table,
  type TableOptionsResolved,
  type Updater,
} from "@tanstack/table-core";
import { Virtualizer, elementScroll, observeElementOffset, observeElementRect } from "@tanstack/virtual-core";
import { el } from "./dom";

export interface GridColumn<T> {
  id: string;
  header: string;
  width: string; // CSS grid track, e.g. "240px" or "minmax(120px,1fr)"
  accessor: (row: T) => string | number | null | undefined;
  cell?: (row: T) => Node | string;
  num?: boolean;
  sortable?: boolean;
}

export interface GridOptions<T> {
  columns: GridColumn<T>[];
  rowHeight?: number;
  rowClass?: (row: T) => string;
  onRowClick?: (row: T) => void;
  initialSort?: SortingState;
  onSortChange?: (s: SortingState) => void;
  ariaLabel: string;
}

const NARROW = () => window.matchMedia("(max-width: 640px)").matches;
const PLAIN_LIMIT = 500;

export class Grid<T> {
  readonly root: HTMLElement;
  private scroller: HTMLElement;
  private head: HTMLElement;
  private body: HTMLElement;
  private table: Table<T>;
  private state: { sorting: SortingState };
  private virt: Virtualizer<HTMLElement, HTMLElement> | null = null;
  private rows: T[] = [];
  private plain = false;
  private template: string;
  private rowHeight: number;

  constructor(private opts: GridOptions<T>) {
    this.rowHeight = opts.rowHeight ?? 40;
    this.template = opts.columns.map((c) => c.width).join(" ");
    this.head = el("div", { class: "ghead", role: "row" });
    this.head.style.gridTemplateColumns = this.template;
    this.body = el("div", { class: "gbody" });
    const grid = el("div", { class: "grid", role: "grid", "aria-label": opts.ariaLabel }, this.head, this.body);
    this.scroller = el("div", { class: "gridwrap" }, grid);
    this.root = this.scroller;
    this.state = { sorting: opts.initialSort ?? [] };
    const columns: ColumnDef<T>[] = opts.columns.map((c) => ({
      id: c.id,
      accessorFn: (r: T) => c.accessor(r),
      enableSorting: c.sortable !== false,
      sortUndefined: "last",
      sortingFn: c.num ? "basic" : "alphanumeric",
    }));
    const options: TableOptionsResolved<T> = {
      data: [],
      columns,
      state: this.state,
      onStateChange: (u: Updater<unknown>) => {
        const next = typeof u === "function" ? (u as (s: unknown) => unknown)(this.state) : u;
        this.state = next as { sorting: SortingState };
        this.table.setOptions((p) => ({ ...p, state: this.state }));
        this.opts.onSortChange?.(this.state.sorting);
        this.renderHead();
        this.renderBody(true);
      },
      renderFallbackValue: null,
      getCoreRowModel: getCoreRowModel(),
      getSortedRowModel: getSortedRowModel(),
    };
    this.table = createTable(options);
    // table-core does not merge partial state with its initial state: supply the full state object.
    this.state = { ...this.table.initialState, sorting: this.state.sorting } as { sorting: SortingState };
    this.table.setOptions((p) => ({ ...p, state: this.state }));
    this.renderHead();
    this.initVirtual();
    window.addEventListener("resize", () => this.renderBody(false));
  }

  private initVirtual(): void {
    this.virt = new Virtualizer<HTMLElement, HTMLElement>({
      count: 0,
      getScrollElement: () => this.scroller,
      estimateSize: () => this.rowHeight,
      overscan: 14,
      scrollToFn: elementScroll,
      observeElementRect,
      observeElementOffset,
      onChange: () => this.paint(),
    });
    this.virt._didMount();
    this.virt._willUpdate();
  }

  setData(rows: T[]): void {
    this.rows = rows;
    this.table.setOptions((p) => ({ ...p, data: rows }));
    this.renderBody(true);
  }

  setSort(s: SortingState): void {
    this.state = { ...this.state, sorting: s };
    this.table.setOptions((p) => ({ ...p, state: this.state }));
    this.renderHead();
    this.renderBody(true);
  }

  getSort(): SortingState {
    return this.state.sorting;
  }

  setPlain(plain: boolean): void {
    this.plain = plain;
    this.renderBody(true);
  }

  sortedRows(): T[] {
    return this.table.getRowModel().rows.map((r) => r.original);
  }

  private renderHead(): void {
    this.head.replaceChildren();
    for (const h of this.table.getHeaderGroups()[0].headers) {
      const col = this.opts.columns.find((c) => c.id === h.column.id)!;
      const dir = h.column.getIsSorted();
      const cell = el("div", { class: `gcell${col.num ? " num" : ""}`, role: "columnheader", tabindex: 0,
        "aria-sort": dir === "asc" ? "ascending" : dir === "desc" ? "descending" : "none" }, col.header);
      if (dir) cell.append(el("span", { class: "dir" }, dir === "asc" ? "▲" : "▼"));
      if (col.sortable !== false) {
        const toggle = (e: Event) => h.column.toggleSorting(undefined, (e as MouseEvent).shiftKey);
        cell.addEventListener("click", toggle);
        cell.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(e); } });
      }
      this.head.append(cell);
    }
  }

  private renderBody(reset: boolean): void {
    const n = this.table.getRowModel().rows.length;
    if (this.plain || NARROW()) {
      this.body.style.height = "";
      this.paintPlain();
      return;
    }
    if (!this.virt) return;
    this.virt.setOptions({ ...this.virt.options, count: n });
    if (reset) this.scroller.scrollTop = 0;
    this.virt.measure();
    this.paint();
  }

  private rowNode(row: T, index: number, top: number | null): HTMLElement {
    const node = el("div", { class: `grow ${this.opts.rowClass?.(row) ?? ""}`.trim(), role: "row", tabindex: 0, "aria-rowindex": index + 2 });
    node.style.gridTemplateColumns = this.template;
    if (top !== null) {
      node.style.transform = `translateY(${top}px)`;
      node.style.height = `${this.rowHeight}px`;
    }
    for (const c of this.opts.columns) {
      const content = c.cell ? c.cell(row) : String(c.accessor(row) ?? "");
      const cell = el("div", { class: `gcell ${c.num ? "num" : "lbl"}`, role: "gridcell", "data-label": c.header });
      cell.append(content);
      node.append(cell);
    }
    const open = () => this.opts.onRowClick?.(row);
    node.addEventListener("click", (e) => { if ((e.target as HTMLElement).closest("a")) return; open(); });
    node.addEventListener("keydown", (e) => { if (e.key === "Enter") open(); });
    return node;
  }

  private paint(): void {
    if (!this.virt || this.plain || NARROW()) return;
    const rows = this.table.getRowModel().rows;
    const items = this.virt.getVirtualItems();
    this.body.style.height = `${this.virt.getTotalSize()}px`;
    this.body.setAttribute("aria-rowcount", String(rows.length));
    const frag = document.createDocumentFragment();
    for (const it of items) {
      const r = rows[it.index];
      if (r) frag.append(this.rowNode(r.original, it.index, it.start));
    }
    this.body.replaceChildren(frag);
  }

  private paintPlain(): void {
    const rows = this.table.getRowModel().rows;
    const frag = document.createDocumentFragment();
    rows.slice(0, PLAIN_LIMIT).forEach((r, i) => frag.append(this.rowNode(r.original, i, null)));
    if (rows.length > PLAIN_LIMIT) frag.append(el("div", { class: "muted", style: "padding:10px" }, `Showing the first ${PLAIN_LIMIT} of ${rows.length} rows. Narrow the filters or use the virtual grid.`));
    this.body.replaceChildren(frag);
  }

  get count(): number {
    return this.rows.length;
  }
}
