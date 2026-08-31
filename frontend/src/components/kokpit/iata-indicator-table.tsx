"use client";

import { ExternalLink } from "lucide-react";
import { useCallback, useState } from "react";

import { DataSourceError, LastUpdatedStamp, StaleDataBanner } from "@/components/data-source-error";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useDataSource } from "@/hooks/use-data-source";
import { apiFetch } from "@/lib/api";
import type { IataIndicatorOut } from "@/lib/types";
import { cn } from "@/lib/utils";

const METRIC_LABEL_TR: Record<string, string> = {
  net_profit: "Net kâr",
  ebit: "Faiz ve vergi öncesi kâr (EBIT)",
  load_factor: "Doluluk oranı",
  passenger_demand: "Yolcu talebi",
  rpk_growth: "RPK büyümesi",
};

const KIND_LABEL: Record<IataIndicatorOut["kind"], string> = {
  actual: "Gerçekleşme",
  forecast: "Tahmin",
};

/** "Önceki tahmin: 72,8 (Ara 2025) ↓" -- one muted line, only where the
 * previous edition's figure is recorded. IATA revises its own forecasts
 * between editions and the revision is often the story (the 2026 net-profit
 * line went from $41bn to $23bn); a card showing only the current number
 * prints the conclusion and drops the news. Rendered as plain text rather
 * than a delta chip on purpose: this is not a market move, it is the same
 * publisher changing its mind, and it must not read like one. */
function RevisionNote({ row }: { row: IataIndicatorOut }) {
  if (row.previous_value === null || row.previous_publication_date === null) return null;

  const edition = new Date(row.previous_publication_date).toLocaleDateString("tr-TR", {
    month: "short",
    year: "numeric",
  });
  const revisedDown = row.value < row.previous_value;
  const arrow = row.value === row.previous_value ? "→" : revisedDown ? "↓" : "↑";
  const arrowLabel =
    row.value === row.previous_value
      ? "değişmedi"
      : revisedDown
        ? "aşağı revize edildi"
        : "yukarı revize edildi";

  return (
    <p className="mt-1 text-[11px] text-muted-foreground">
      Önceki tahmin: {row.previous_value.toLocaleString("tr-TR")} ({edition}){" "}
      <span aria-label={arrowLabel} title={arrowLabel}>
        {arrow}
      </span>
    </p>
  );
}

const tab = (active: boolean) =>
  cn(
    "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
    active ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent",
  );

/** IATA's own published figures, forecast and actual kept structurally
 * separate -- see backend/app/models/curated.py's INDICATOR_KINDS. */
export function IataIndicatorTable() {
  const [kind, setKind] = useState<IataIndicatorOut["kind"]>("forecast");

  const fetcher = useCallback(
    (signal: AbortSignal) =>
      apiFetch<IataIndicatorOut[]>(`/kokpit/iata?kind=${kind}`, { cache: "default", signal }),
    [kind],
  );
  const { data: rows, error, loaded, lastUpdated, stale, retry } = useDataSource(fetcher, [kind]);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex w-fit items-center gap-1 self-start rounded-lg border border-border p-0.5">
        {(["forecast", "actual"] as const).map((k) => (
          <button key={k} type="button" onClick={() => setKind(k)} className={tab(kind === k)}>
            {KIND_LABEL[k]}
          </button>
        ))}
      </div>

      {stale && <StaleDataBanner onRetry={retry} lastUpdated={lastUpdated} />}

      {!loaded ? (
        <Skeleton className="h-48 w-full rounded-xl" />
      ) : error && !rows ? (
        <DataSourceError onRetry={retry} lastUpdated={lastUpdated} />
      ) : !rows || rows.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">
          Bu tür için henüz küratörlü bir IATA göstergesi yok.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {rows.map((row) => (
            <Card key={`${row.metric}-${row.period_end}`} className="p-4">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="text-sm font-semibold">
                    {METRIC_LABEL_TR[row.metric] ?? row.metric}
                  </p>
                  <p className="text-[11px] text-muted-foreground">{row.period_label_tr}</p>
                </div>
                <a
                  href={row.source_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label="Kaynağa git"
                  className="text-muted-foreground hover:text-primary"
                >
                  <ExternalLink className="size-3.5" />
                </a>
              </div>
              <p className="mt-2 text-2xl font-semibold tabular-nums">
                {row.value.toLocaleString("tr-TR")}
                <span className="ml-1 text-sm font-normal text-muted-foreground">{row.unit}</span>
              </p>
              <RevisionNote row={row} />
              {row.interpretation_tr && (
                <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                  {row.interpretation_tr}
                </p>
              )}
            </Card>
          ))}
        </div>
      )}
      <LastUpdatedStamp date={lastUpdated} />
    </div>
  );
}
