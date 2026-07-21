"use client";

import { ArrowLeftRight, Download } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Skeleton } from "@/components/ui/skeleton";
import { apiFetch } from "@/lib/api";
import { airlineTabs, worldRegions } from "@/lib/nav";
import { CATEGORIES, CATEGORY_BY_SLUG } from "@/lib/taxonomy";
import { cn } from "@/lib/utils";

// Types live here rather than in lib/types.ts: this payload is shaped by the
// pivot endpoint alone and is never rendered by another component.
interface PivotDimension {
  slug: string;
  label: string;
  chronological: boolean;
}

interface PivotMeasure {
  slug: string;
  label: string;
  decimals: number;
}

interface PivotMeta {
  dimensions: PivotDimension[];
  measures: PivotMeasure[];
  filters: string[];
  default_days: number;
}

interface PivotOut {
  rows: string[];
  cols: string[];
  /** Keyed "satır|sütun". Combinations with no articles are simply absent. */
  cells: Record<string, number | null>;
  row_totals: Record<string, number | null>;
  col_totals: Record<string, number | null>;
  grand_total: number | null;
  measure: string;
  measure_label: string;
  decimals: number;
  truncated: boolean;
  dimensions: {
    rows: string;
    rows_label: string;
    cols: string | null;
    cols_label: string | null;
  };
}

const DAY_RANGES = [
  { days: 7, label: "7 gün" },
  { days: 30, label: "30 gün" },
  { days: 90, label: "90 gün" },
  { days: 365, label: "1 yıl" },
];

const SENTIMENT_LABELS: Record<string, string> = {
  positive: "Olumlu",
  neutral: "Nötr",
  negative: "Olumsuz",
};

const REGION_LABELS: Record<string, string> = Object.fromEntries(
  worldRegions.map((region) => [region.slug, region.name]),
);

const AIRLINE_NAMES: Record<string, string> = Object.fromEntries(
  airlineTabs.map((airline) => [airline.code, airline.name]),
);

const SUBCATEGORY_LABELS: Record<string, string> = Object.fromEntries(
  CATEGORIES.flatMap((category) =>
    category.subcategories.map((sub) => [sub.slug, sub.label]),
  ),
);

const MONTH_NAMES = [
  "Oca", "Şub", "Mar", "Nis", "May", "Haz",
  "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara",
];

/** Backend sends taxonomy slugs; the Turkish labels are frontend-only (same
 * split as the newspaper). Anything unmapped -- a source name, an IATA code we
 * don't carry a logo for -- is shown verbatim. */
function valueLabel(dimension: string | null, value: string): string {
  switch (dimension) {
    case "category":
      return CATEGORY_BY_SLUG[value]?.label ?? value;
    case "subcategory":
      return SUBCATEGORY_LABELS[value] ?? value;
    case "region":
      return REGION_LABELS[value] ?? value;
    case "sentiment":
      return SENTIMENT_LABELS[value] ?? value;
    case "airline":
      return AIRLINE_NAMES[value] ? `${value} · ${AIRLINE_NAMES[value]}` : value;
    case "day":
    case "week": {
      const parts = value.split("-");
      if (parts.length !== 3) return value;
      const label = `${Number(parts[2])} ${MONTH_NAMES[Number(parts[1]) - 1] ?? ""}`;
      return dimension === "week" ? `${label} haftası` : label;
    }
    case "month": {
      const parts = value.split("-");
      if (parts.length !== 2) return value;
      return `${MONTH_NAMES[Number(parts[1]) - 1] ?? parts[1]} ${parts[0]}`;
    }
    default:
      return value;
  }
}

function formatNumber(value: number | null | undefined, decimals: number): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("tr-TR", { maximumFractionDigits: decimals });
}

/** Sequential single-hue ramp keyed to the app's validated blue (--primary is
 * #2a78d6 in light, #3987e5 in dark), so the heatmap follows the theme without
 * a second palette. Opacity stops at 58%: past that the cell text stops
 * clearing contrast in one of the two themes. */
function heatStyle(value: number | null | undefined, max: number) {
  if (!value || value <= 0 || max <= 0) return undefined;
  const share = Math.min(1, value / max);
  return {
    backgroundColor: `color-mix(in srgb, var(--primary) ${(8 + share * 50).toFixed(1)}%, transparent)`,
  };
}

function csvCell(value: string): string {
  return /[";\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

interface ChipRowProps<T extends string | number> {
  label: string;
  options: { value: T | null; label: string }[];
  value: T | null;
  onChange: (value: T | null) => void;
}

function ChipRow<T extends string | number>({
  label,
  options,
  value,
  onChange,
}: ChipRowProps<T>) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      {options.map((option) => (
        <button
          key={String(option.value)}
          onClick={() => onChange(option.value)}
          className={cn(
            "rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
            option.value === value
              ? "bg-primary text-primary-foreground"
              : "border border-border text-muted-foreground hover:bg-accent",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

const SELECT_CLASS =
  "rounded-md border border-border bg-card px-2.5 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-accent focus:outline-none focus:ring-2 focus:ring-ring";

export function PivotClient() {
  const [meta, setMeta] = useState<PivotMeta | null>(null);
  const [rowDim, setRowDim] = useState("category");
  const [colDim, setColDim] = useState<string>("month");
  const [measure, setMeasure] = useState("count");

  const [days, setDays] = useState(30);
  const [category, setCategory] = useState<string | null>(null);
  const [region, setRegion] = useState<string | null>(null);
  const [airline, setAirline] = useState<string | null>(null);

  const [loaded, setLoaded] = useState<{ key: string; data: PivotOut } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const query = useMemo(() => {
    const params = new URLSearchParams({ rows: rowDim, measure, days: String(days) });
    if (colDim && colDim !== rowDim) params.set("cols", colDim);
    if (category) params.set("category", category);
    if (region) params.set("region", region);
    if (airline) params.set("airline", airline);
    return params.toString();
  }, [rowDim, colDim, measure, days, category, region, airline]);

  // The whitelist drives the pickers, so the UI can never offer a dimension
  // the API would answer with a 400.
  useEffect(() => {
    const controller = new AbortController();
    apiFetch<PivotMeta>("/pivot/dimensions", {
      cache: "default",
      signal: controller.signal,
    })
      .then(setMeta)
      .catch(() => {
        /* the table's own error state covers a dead backend */
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    apiFetch<PivotOut>(`/pivot?${query}`, { cache: "default", signal: controller.signal })
      .then((data) => {
        setLoaded({ key: query, data });
        setError(null);
      })
      .catch((cause: unknown) => {
        if ((cause as Error)?.name === "AbortError") return;
        setError("Analiz yüklenemedi. Sunucu çalışıyor mu?");
      });
    return () => controller.abort();
  }, [query]);

  // Derived rather than stored, so no state is set during the effect body and
  // a stale response can never leave the table claiming to be current.
  const pivot = loaded?.key === query ? loaded.data : null;
  const stale = loaded !== null && loaded.key !== query;

  const maxCell = useMemo(() => {
    if (!pivot) return 0;
    const pool = pivot.cols.length
      ? Object.values(pivot.cells)
      : Object.values(pivot.row_totals);
    return pool.reduce<number>((max, value) => Math.max(max, value ?? 0), 0);
  }, [pivot]);

  function downloadCsv() {
    if (!pivot) return;
    const header = [
      pivot.dimensions.rows_label,
      ...pivot.cols.map((col) => valueLabel(pivot.dimensions.cols, col)),
      "Toplam",
    ];
    const number = (value: number | null | undefined) =>
      value === null || value === undefined ? "" : String(value).replace(".", ",");
    const lines = [
      header.map(csvCell).join(";"),
      ...pivot.rows.map((row) =>
        [
          csvCell(valueLabel(pivot.dimensions.rows, row)),
          ...pivot.cols.map((col) => number(pivot.cells[`${row}|${col}`])),
          number(pivot.row_totals[row]),
        ].join(";"),
      ),
      [
        "Toplam",
        ...pivot.cols.map((col) => number(pivot.col_totals[col])),
        number(pivot.grand_total),
      ].join(";"),
    ];
    // BOM + ";" so Turkish Excel opens the columns split and the ş/ğ/ı intact.
    const blob = new Blob(["﻿" + lines.join("\r\n")], {
      type: "text/csv;charset=utf-8;",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `analiz-${rowDim}-${pivot.dimensions.cols ?? "toplam"}-${measure}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  function swapAxes() {
    if (!pivot?.dimensions.cols) return;
    setRowDim(pivot.dimensions.cols);
    setColDim(rowDim);
  }

  const dimensions = meta?.dimensions ?? [];
  const measures = meta?.measures ?? [];
  const decimals = pivot?.decimals ?? 0;
  const headCell =
    "sticky left-0 z-10 bg-card px-3 py-2 text-left text-xs font-semibold";

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-2xl font-semibold tracking-tight">Analiz</h1>
          <p className="text-sm text-muted-foreground">
            Satır, sütun ve değer ata; haber arşivini kendi pivot tablona çevir.
          </p>
        </div>
        <button
          onClick={downloadCsv}
          disabled={!pivot || pivot.rows.length === 0}
          className="flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40"
        >
          <Download className="size-3.5" />
          CSV indir
        </button>
      </div>

      {/* Row / column / value assignment */}
      <div className="flex flex-wrap items-end gap-4 rounded-xl border border-border bg-card p-4">
        <label className="flex flex-col gap-1">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Satır
          </span>
          <select
            value={rowDim}
            onChange={(event) => setRowDim(event.target.value)}
            className={SELECT_CLASS}
          >
            {dimensions.map((dimension) => (
              <option key={dimension.slug} value={dimension.slug}>
                {dimension.label}
              </option>
            ))}
          </select>
        </label>

        <button
          onClick={swapAxes}
          disabled={!pivot?.dimensions.cols}
          title="Satır ve sütunu yer değiştir"
          aria-label="Satır ve sütunu yer değiştir"
          className="mb-1 rounded-md border border-border p-2 text-muted-foreground transition-colors hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40"
        >
          <ArrowLeftRight className="size-3.5" />
        </button>

        <label className="flex flex-col gap-1">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Sütun
          </span>
          <select
            value={colDim}
            onChange={(event) => setColDim(event.target.value)}
            className={SELECT_CLASS}
          >
            <option value="">— yok (yalnız toplam) —</option>
            {dimensions.map((dimension) => (
              <option
                key={dimension.slug}
                value={dimension.slug}
                disabled={dimension.slug === rowDim}
              >
                {dimension.label}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
            Değer
          </span>
          <select
            value={measure}
            onChange={(event) => setMeasure(event.target.value)}
            className={SELECT_CLASS}
          >
            {measures.map((item) => (
              <option key={item.slug} value={item.slug}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {/* Filters -- same chip language as the newspaper's filter row */}
      <div className="flex flex-col gap-2">
        <ChipRow
          label="Tarih"
          value={days}
          onChange={(value) => setDays(value ?? 30)}
          options={DAY_RANGES.map((range) => ({ value: range.days, label: range.label }))}
        />
        <ChipRow
          label="Kategori"
          value={category}
          onChange={setCategory}
          options={[
            { value: null, label: "Tümü" },
            ...[...CATEGORIES]
              .sort((a, b) => a.label.localeCompare(b.label, "tr"))
              .map((item) => ({ value: item.slug, label: item.label })),
          ]}
        />
        <ChipRow
          label="Bölge"
          value={region}
          onChange={setRegion}
          options={[
            { value: null, label: "Tümü" },
            ...worldRegions.map((item) => ({ value: item.slug, label: item.name })),
          ]}
        />
        <ChipRow
          label="Havayolu"
          value={airline}
          onChange={setAirline}
          options={[
            { value: null, label: "Tümü" },
            { value: "RIVALS", label: "Ana Rakipler" },
            { value: "ALL", label: "Tüm Taşıyıcılar" },
            ...airlineTabs.map((item) => ({ value: item.code, label: item.code })),
          ]}
        />
      </div>

      {error && (
        <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
          {error}
        </p>
      )}

      {!error && !pivot && <Skeleton className="h-96 w-full rounded-xl" />}

      {!error && pivot && pivot.rows.length === 0 && (
        <p className="rounded-lg border border-dashed border-border p-6 text-sm text-muted-foreground">
          Bu filtrelerle eşleşen haber yok. Tarih aralığını genişletmeyi ya da kategori /
          bölge / havayolu filtrelerinden birini kaldırmayı deneyin.
        </p>
      )}

      {!error && pivot && pivot.rows.length > 0 && (
        <div className={cn("flex flex-col gap-2", stale && "opacity-60")}>
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-sm text-muted-foreground">
              <span className="font-medium text-foreground">{pivot.measure_label}</span>
              {" · "}
              {pivot.dimensions.rows_label}
              {pivot.dimensions.cols_label ? ` × ${pivot.dimensions.cols_label}` : ""}
              {" · son "}
              {days} gün
            </p>
            {pivot.truncated && (
              <p className="text-[11px] text-muted-foreground">
                Tablo en büyük satır ve sütunlarla sınırlandı; toplamlar tüm veriyi kapsar.
              </p>
            )}
          </div>

          {/* The pivot can be much wider than the page; it scrolls inside this
              wrapper so the page itself never scrolls sideways. */}
          <div className="overflow-x-auto rounded-xl border border-border bg-card">
            <table className="w-full min-w-max border-collapse text-sm [font-variant-numeric:tabular-nums]">
              <thead>
                <tr className="border-b border-border">
                  <th className={cn(headCell, "text-muted-foreground")}>
                    {pivot.dimensions.rows_label}
                    {pivot.dimensions.cols_label
                      ? ` \\ ${pivot.dimensions.cols_label}`
                      : ""}
                  </th>
                  {pivot.cols.map((col) => (
                    <th
                      key={col}
                      scope="col"
                      className="px-3 py-2 text-right text-xs font-semibold text-muted-foreground"
                    >
                      {valueLabel(pivot.dimensions.cols, col)}
                    </th>
                  ))}
                  <th
                    scope="col"
                    className="px-3 py-2 text-right text-xs font-semibold text-foreground"
                  >
                    Toplam
                  </th>
                </tr>
              </thead>
              <tbody>
                {pivot.rows.map((row) => (
                  <tr key={row} className="border-b border-border/60 last:border-0">
                    <th scope="row" className={cn(headCell, "font-medium")}>
                      {valueLabel(pivot.dimensions.rows, row)}
                    </th>
                    {pivot.cols.map((col) => {
                      const value = pivot.cells[`${row}|${col}`];
                      return (
                        <td
                          key={col}
                          style={heatStyle(value, maxCell)}
                          className="px-3 py-1.5 text-right"
                        >
                          {value === undefined ? (
                            <span className="text-muted-foreground/50">·</span>
                          ) : (
                            formatNumber(value, decimals)
                          )}
                        </td>
                      );
                    })}
                    <td
                      style={pivot.cols.length ? undefined : heatStyle(pivot.row_totals[row], maxCell)}
                      className="px-3 py-1.5 text-right font-semibold"
                    >
                      {formatNumber(pivot.row_totals[row], decimals)}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-border">
                  <th scope="row" className={cn(headCell, "font-semibold")}>
                    Toplam
                  </th>
                  {pivot.cols.map((col) => (
                    <td key={col} className="px-3 py-2 text-right font-semibold">
                      {formatNumber(pivot.col_totals[col], decimals)}
                    </td>
                  ))}
                  <td className="px-3 py-2 text-right font-semibold text-primary">
                    {formatNumber(pivot.grand_total, decimals)}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>

          <p className="text-[11px] leading-relaxed text-muted-foreground">
            Yinelenen haberler her zaman hariç tutulur. Toplam satırı ve sütunu, hücrelerin
            toplamı değil; veritabanında aynı filtrelerle yeniden hesaplanmış değerlerdir —
            &ldquo;farklı kaynak&rdquo; ve ortalama ölçüleri toplanabilir olmadığı için.
            Havayolu boyutunda birden çok taşıyıcıdan söz eden bir haber her taşıyıcının
            altında sayılır.
          </p>
        </div>
      )}
    </div>
  );
}
