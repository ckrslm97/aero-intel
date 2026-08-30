"use client";

import { ExternalLink } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { DataSourceError, LastUpdatedStamp, StaleDataBanner } from "@/components/data-source-error";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useDataSource } from "@/hooks/use-data-source";
import { apiFetch } from "@/lib/api";
import { formatRate } from "@/lib/format";
import type { FxForecastOut } from "@/lib/types";
import { cn } from "@/lib/utils";

const chip = (active: boolean) =>
  cn(
    "rounded-full px-2.5 py-1 text-xs font-medium transition-colors",
    active
      ? "bg-primary/12 text-primary ring-1 ring-primary/40 dark:glow-soft"
      : "border border-border text-muted-foreground hover:bg-accent",
  );

interface RangeGroup {
  pair: string;
  min: number;
  max: number;
  rows: FxForecastOut[];
}

/** Where each institution's dot sits inside its own group's min..max span.
 * A single-forecast group collapses to one dot at the left end rather than
 * dividing by zero. */
function dotOffsetPct(value: number, min: number, max: number): number {
  if (max === min) return 0;
  return ((value - min) / (max - min)) * 100;
}

/** The spread of published forecasts for one pair -- NOT a consensus.
 *
 * There is deliberately no average, median or "piyasa beklentisi" number
 * anywhere in this component. The module that curates these rows
 * (backend/app/ingest/curated_seed.py) forbids it by design: institutions
 * publishing for differently-worded horizons do not have a mean that means
 * anything, and printing one would turn four attributable claims into one
 * unattributable invention.
 *
 * The horizons are NOT normalised either, which is why this bar groups by pair
 * alone and then says "farklı vadeler" out loud. Bucketing Garanti's "yıl
 * sonu" together with JPMorgan's "end-2026" would be exactly the judgement the
 * curation module refuses to make -- and with every row carrying its own
 * wording, a strict (pair, horizon) grouping produced no group larger than one
 * and the bar never rendered at all.
 *
 * So what it claims is only what is true: these are the published numbers for
 * this pair, they span this range, they are for different horizons, and each
 * dot is one institution's own figure with its own horizon in the hover.
 */
function ForecastRangeBar({ group }: { group: RangeGroup }) {
  const spreadPct = group.min ? ((group.max - group.min) / group.min) * 100 : 0;
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-border bg-card/60 px-3 py-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[11px] font-semibold">{group.pair}</span>
        <span className="truncate text-[10px] text-muted-foreground">
          {group.rows.length} kurum · farklı vadeler
        </span>
      </div>
      <div className="relative h-4">
        <span
          aria-hidden
          className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-gradient-to-r from-primary/25 via-primary/40 to-primary/25"
        />
        {group.rows.map((row) => (
          <span
            key={`${row.institution}-${row.horizon_label}`}
            title={`${row.institution} · ${row.horizon_label}: ${formatRate(row.value, 4)}`}
            style={{ left: `${dotOffsetPct(row.value, group.min, group.max)}%` }}
            className="absolute top-1/2 size-2 -translate-x-1/2 -translate-y-1/2 cursor-help rounded-full bg-primary ring-2 ring-card"
          />
        ))}
      </div>
      <div className="flex items-baseline justify-between text-[10px] tabular-nums text-muted-foreground">
        <span>{formatRate(group.min, 4)}</span>
        <span className="text-[9px]">aralık %{spreadPct.toFixed(0)}</span>
        <span>{formatRate(group.max, 4)}</span>
      </div>
    </div>
  );
}

/** Curated bank FX forecasts -- see backend/app/ingest/curated_seed.py.
 * Every row is one institution's own, individually-attributed number: never
 * averaged, never re-labelled onto a normalised horizon. */
export function FxForecastTable() {
  const [pair, setPair] = useState<string | null>(null);
  const [horizon, setHorizon] = useState<string | null>(null);

  const fetcher = useCallback(
    (signal: AbortSignal) =>
      apiFetch<FxForecastOut[]>("/kokpit/fx-forecasts", { cache: "default", signal }),
    [],
  );
  const { data: rows, error, loaded, lastUpdated, stale, retry } = useDataSource(fetcher, []);

  const pairs = useMemo(
    () => [...new Set((rows ?? []).map((r) => r.currency_pair))].sort(),
    [rows],
  );
  // Horizon labels are each institution's own wording, so this is a flat set
  // of the labels actually present -- not a normalised "1m/3m/12m" bucket,
  // which would be exactly the interpolation the module this reads from
  // (curated_seed.py) exists to avoid.
  const horizons = useMemo(
    () => [...new Set((rows ?? []).map((r) => r.horizon_label))].sort(),
    [rows],
  );
  const filtered = useMemo(
    () =>
      (rows ?? []).filter(
        (r) =>
          (!pair || r.currency_pair === pair) && (!horizon || r.horizon_label === horizon),
      ),
    [rows, pair, horizon],
  );

  // Grouped by pair only -- see ForecastRangeBar for why the horizons are not
  // bucketed. A pair with a single published forecast gets no bar: a "range"
  // of one is just the number, and it is already in the table below.
  const ranges = useMemo<RangeGroup[]>(() => {
    const groups = new Map<string, RangeGroup>();
    for (const row of filtered) {
      const existing = groups.get(row.currency_pair);
      if (existing) {
        existing.rows.push(row);
        existing.min = Math.min(existing.min, row.value);
        existing.max = Math.max(existing.max, row.value);
      } else {
        groups.set(row.currency_pair, {
          pair: row.currency_pair,
          min: row.value,
          max: row.value,
          rows: [row],
        });
      }
    }
    return [...groups.values()]
      .filter((group) => group.rows.length > 1)
      .sort((a, b) => a.pair.localeCompare(b.pair));
  }, [filtered]);

  if (!loaded) {
    return <Skeleton className="h-64 w-full rounded-xl" />;
  }
  if (error && !rows) {
    return <DataSourceError onRetry={retry} lastUpdated={lastUpdated} />;
  }
  if (!rows || rows.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">
        Henüz küratörlü bir banka tahmini yok.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {stale && <StaleDataBanner onRetry={retry} lastUpdated={lastUpdated} />}
      <div className="flex flex-wrap gap-1.5">
        <button type="button" onClick={() => setPair(null)} className={chip(!pair)}>
          Tümü
        </button>
        {pairs.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => setPair(pair === p ? null : p)}
            className={chip(pair === p)}
          >
            {p}
          </button>
        ))}
        <span aria-hidden className="mx-0.5 h-4 w-px self-center bg-border" />
        <span className="self-center text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Vade
        </span>
        {horizons.map((h) => (
          <button
            key={h}
            type="button"
            onClick={() => setHorizon(horizon === h ? null : h)}
            className={chip(horizon === h)}
          >
            {h}
          </button>
        ))}
      </div>

      {ranges.length > 0 && (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {ranges.map((group) => (
            <ForecastRangeBar key={group.pair} group={group} />
          ))}
        </div>
      )}

      <Card className="overflow-x-auto">
        <table className="w-full min-w-[36rem] text-sm">
          <thead>
            <tr className="border-b border-border text-left text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              <th className="px-4 py-2.5">Kurum</th>
              <th className="px-4 py-2.5">Parite</th>
              <th className="px-4 py-2.5">Vade</th>
              <th className="px-4 py-2.5 text-right">Tahmin</th>
              <th className="px-4 py-2.5">Yayın tarihi</th>
              <th className="px-4 py-2.5" />
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {filtered.map((row) => (
              <tr key={`${row.institution}-${row.currency_pair}-${row.horizon_label}`}>
                <td className="px-4 py-2.5 font-medium">{row.institution}</td>
                <td className="px-4 py-2.5 text-muted-foreground">{row.currency_pair}</td>
                {/* The institution's own wording, verbatim -- never normalised
                    onto a shared "3 ay" column. */}
                <td className="px-4 py-2.5 text-muted-foreground">{row.horizon_label}</td>
                <td className="px-4 py-2.5 text-right font-semibold tabular-nums">
                  {formatRate(row.value, 4)}
                </td>
                <td className="px-4 py-2.5 text-muted-foreground">
                  {new Date(row.publication_date).toLocaleDateString("tr-TR", {
                    day: "numeric",
                    month: "short",
                    year: "numeric",
                  })}
                </td>
                <td className="px-4 py-2.5">
                  <a
                    href={row.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={`${row.institution} kaynağına git`}
                    className="flex items-center text-muted-foreground hover:text-primary"
                  >
                    <ExternalLink className="size-3.5" />
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <LastUpdatedStamp date={lastUpdated} />
    </div>
  );
}
